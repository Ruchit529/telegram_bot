import asyncio
import hashlib
import re
import time
import urllib.parse
from typing import Dict, Tuple, List, Optional
import httpx
from deep_translator import GoogleTranslator
from deep_translator.exceptions import BaseError
from langdetect import detect, LangDetectException

from config import logger, DEFAULT_TARGET_LANGUAGE, TRANSLATION_RATE_LIMIT
from database import db

class TranslationService:
    def __init__(self):
        # Memory cache of recent translations to avoid DB calls
        self._memory_cache: Dict[str, str] = {}
        self._last_api_call_time = 0.0
        self._api_call_lock = asyncio.Lock()

    def _get_hash(self, text: str) -> str:
        """Returns the MD5 hash of the text to use as a database and memory cache key."""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _extract_placeholders(self, html_text: str) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Extracts HTML tags, hashtags, and raw URLs, replacing them with unique non-word tokens
        (e.g. XZXTAG0XZX, XZXURL0XZX, XZXHASH0XZX) to preserve them safely during translation.
        Returns: (protected_text, [(token, original_val), ...])
        """
        placeholders = []
        temp_text = html_text

        # 1. Protect HTML Tags (e.g. <a href="...">, <b>, </i>, etc.)
        def tag_replacer(match):
            token = f"XZXTAG{len(placeholders)}XZX"
            val = match.group(0)
            placeholders.append((token, val))
            return token
        temp_text = re.sub(r"<[^>]+>", tag_replacer, temp_text)

        # 2. Protect raw URLs that aren't inside HTML tags already
        def url_replacer(match):
            token = f"XZXURL{len(placeholders)}XZX"
            val = match.group(0)
            placeholders.append((token, val))
            return token
        temp_text = re.sub(r"https?://[^\s<>]+", url_replacer, temp_text)

        # 3. Protect Hashtags
        def hashtag_replacer(match):
            token = f"XZXHASH{len(placeholders)}XZX"
            val = match.group(0)
            placeholders.append((token, val))
            return token
        temp_text = re.sub(r"(?<!\w)#\w+", hashtag_replacer, temp_text)

        return temp_text, placeholders

    def _restore_placeholders(self, translated_text: str, placeholders: List[Tuple[str, str]]) -> str:
        """
        Ultra-resilient restoration of HTML tags, URLs, and hashtags back into translated text.
        Handles casing, extra spaces, translated dictionary words (e.g. TAG -> DAY/BALISE), or mangled brackets.
        """
        restored = translated_text
        for idx, (token, original_val) in enumerate(placeholders):
            # Extract token type (TAG, URL, HASH)
            token_type = "TAG" if "TAG" in token else "URL" if "URL" in token else "HASH"
            
            # Match variants: XZXTAG0XZX, XZX TAG 0 XZX, __TAG_0__, __DAY_0__, etc.
            pattern_str = r"(?:XZX|__|\[|\{)*\s*(?:" + token_type + r"|DAY|BALISE|ETIQUETA)\s*[-_]?\s*" + str(idx) + r"\s*(?:XZX|__|\]|\})*"
            pattern = re.compile(pattern_str, re.IGNORECASE)
            
            if pattern.search(restored):
                restored = pattern.sub(original_val, restored)
            else:
                # Fallback to direct literal token string replacement
                restored = restored.replace(token, original_val)

        # Clean up any leftover duplicate spaces around tags
        restored = re.sub(r" +", " ", restored).strip()
        return restored

    def _is_invalid_translation(self, text: str) -> bool:
        """
        Checks if the translator returned a scraped HTTP error page, rate-limit error,
        query limit error, or MyMemory quota warning instead of actual translated text.
        """
        if not text or not text.strip():
            return True
        
        lowered = text.lower()
        error_indicators = [
            "error 500",
            "500(servererror)",
            "500. that's an error",
            "500. thats an error",
            "servererror",
            "500 internal server error",
            "429 too many requests",
            "403 forbidden",
            "that's an error",
            "thats an error",
            "there was an error",
            "<!doctype html>",
            "<html",
            "<title>error",
            "mymemory warning",
            "you used all your free quota",
            "quota exceeded",
            "rate limit",
            "invalid key",
            "query length limit exceeded",
            "max allowed query",
            "500 chars"
        ]
        
        for indicator in error_indicators:
            if indicator in lowered:
                return True
                
        return False

    def _chunk_text(self, text: str, max_chars: int = 400) -> List[str]:
        """
        Splits long text into safe chunks of <= max_chars (default 400)
        to prevent triggering character limit errors (500-char limits) in translation APIs.
        """
        if len(text) <= max_chars:
            return [text]

        chunks = []
        lines = text.split("\n")
        current_chunk = ""

        for line in lines:
            if len(line) > max_chars:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                # Split long line by words
                words = line.split(" ")
                sub_chunk = ""
                for word in words:
                    if len(sub_chunk) + len(word) + 1 <= max_chars:
                        sub_chunk = f"{sub_chunk} {word}".strip()
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk)
                        sub_chunk = word
                if sub_chunk:
                    chunks.append(sub_chunk)
            else:
                if len(current_chunk) + len(line) + 1 <= max_chars:
                    current_chunk = f"{current_chunk}\n{line}" if current_chunk else line
                else:
                    chunks.append(current_chunk)
                    current_chunk = line

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [text]

    async def detect_language(self, text: str) -> str:
        """
        Detects language of incoming text.
        Strips HTML tags, URLs, hashtags, and numbers first to avoid misclassification.
        """
        clean_text = re.sub(r"<[^>]+>", "", text)
        clean_text = re.sub(r"#\w+", "", clean_text)
        clean_text = re.sub(r"https?://[^\s<>]+", "", clean_text)
        clean_text = re.sub(r"\b[\d\.\_]+\b", "", clean_text).strip()

        # If too short or mostly symbols, assume English
        if not clean_text or len(re.sub(r"[^\w]", "", clean_text)) < 3:
            return "en"

        # Direct Script Range Checks (Cyrillic, Hindi, Arabic, Chinese/Japanese, Korean)
        if re.search(r"[\u0400-\u04FF]", clean_text):
            return "ru"  # Cyrillic
        if re.search(r"[\u0900-\u097F]", clean_text):
            return "hi"  # Devanagari / Hindi
        if re.search(r"[\u0600-\u06FF]", clean_text):
            return "ar"  # Arabic
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", clean_text):
            return "ja"  # Japanese/CJK
        if re.search(r"[\uac00-\ud7af]", clean_text):
            return "ko"  # Korean

        # Single-pass langdetect check
        try:
            detected = await asyncio.to_thread(detect, clean_text)
            return detected
        except Exception:
            return "auto"

    async def _translate_google_gtx(self, text: str, target_lang: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Primary high-speed translation engine using Google's official GTX REST endpoint.
        Fast, reliable, bypasses web scraping blocks, returns clean JSON.
        """
        try:
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "dt": "t",
                "sl": "auto",
                "tl": target_lang,
                "q": text
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(url, params=params, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    if data and isinstance(data, list) and len(data) > 0 and data[0]:
                        chunks = [chunk[0] for chunk in data[0] if chunk and chunk[0]]
                        translated_text = "".join(chunks)
                        detected_lang = data[2] if len(data) > 2 and isinstance(data[2], str) else "auto"
                        if translated_text and not self._is_invalid_translation(translated_text):
                            return translated_text, detected_lang
        except Exception as e:
            logger.warning(f"Google GTX REST API translation failed: {e}")
        return None, None

    async def _translate_google_scraping(self, text: str, target_lang: str) -> Optional[str]:
        """Secondary failover using deep_translator GoogleTranslator."""
        try:
            translator = GoogleTranslator(source="auto", target=target_lang)
            res = await asyncio.to_thread(translator.translate, text)
            if res and not self._is_invalid_translation(res):
                return res
        except BaseError as e:
            logger.warning(f"GoogleTranslator Scraping API Error: {e}")
        except Exception as e:
            logger.warning(f"GoogleTranslator Scraping unexpected error: {e}")
        return None

    async def _translate_mymemory(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        """Tertiary fast failover translator using MyMemory API."""
        try:
            src = source_lang if source_lang and source_lang != 'auto' else 'autodetect'
            langpair = f"{src}|{target_lang}"
            url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair={langpair}"
            
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    translated = data.get("responseData", {}).get("translatedText")
                    if translated and not self._is_invalid_translation(translated):
                        clean_res = re.sub(r"^<p>|</p>$", "", translated.strip(), flags=re.IGNORECASE)
                        return clean_res
        except Exception as e:
            logger.warning(f"MyMemory failover translation failed: {e}")
        return None

    async def _translate_chunk(self, chunk: str, target_lang: str) -> Tuple[str, str]:
        """Translates a single chunk (<= 400 chars) through the multi-engine failover chain."""
        if not chunk or not chunk.strip():
            return chunk, "en"

        # Engine 1: Google GTX REST API
        gtx_res, gtx_lang = await self._translate_google_gtx(chunk, target_lang)
        if gtx_res and not self._is_invalid_translation(gtx_res):
            return gtx_res, gtx_lang or "auto"

        # Engine 2: GoogleTranslator Scraping
        scraping_res = await self._translate_google_scraping(chunk, target_lang)
        if scraping_res and not self._is_invalid_translation(scraping_res):
            return scraping_res, "auto"

        # Engine 3: MyMemory API
        mymemory_res = await self._translate_mymemory(chunk, "auto", target_lang)
        if mymemory_res and not self._is_invalid_translation(mymemory_res):
            return mymemory_res, "auto"

        # Fallback if all engines fail for this chunk
        return chunk, "auto"

    async def translate_html(
        self, html_text: str, target_lang: str = DEFAULT_TARGET_LANGUAGE
    ) -> Tuple[str, str, bool]:
        """
        Translates HTML text/caption to target language (e.g. 'en') while preserving formatting.
        Automatically chunks long posts into <= 400 char blocks to prevent 500-char query limit errors.
        Returns: (translated_html, detected_language, was_translated_bool)
        """
        if not html_text or not html_text.strip():
            return "", "en", False

        text_hash = self._get_hash(html_text)

        # 1. Check Memory Cache
        cache_key = f"{text_hash}:{target_lang}"
        if cache_key in self._memory_cache:
            cached_text = self._memory_cache[cache_key]
            if not self._is_invalid_translation(cached_text):
                logger.debug("Translation found in memory cache.")
                return cached_text, "auto", True
            else:
                del self._memory_cache[cache_key]

        # 2. Check Database Cache
        db_cache = await db.get_cached_translation(text_hash)
        if db_cache:
            source_lang, translated_text = db_cache
            if not self._is_invalid_translation(translated_text):
                self._memory_cache[cache_key] = translated_text
                logger.debug("Translation found in database cache.")
                return translated_text, source_lang, source_lang != target_lang

        # 3. Protect formatting/tags/links
        protected_text, placeholders = self._extract_placeholders(html_text)
        
        # If there are no alphabetical words to translate after stripping placeholders, skip
        words_only = re.sub(r"XZX(TAG|URL|HASH)\d+XZX", "", protected_text)
        if not re.sub(r"[^\w]", "", words_only).strip():
            return html_text, "en", False

        # 4. Multiprovider Failover Translation Execution with Smart Chunking
        chunks = self._chunk_text(protected_text, max_chars=400)
        translated_chunks = []
        detected_lang = "auto"
        
        async with self._api_call_lock:
            now = time.time()
            elapsed = now - self._last_api_call_time
            if elapsed < TRANSLATION_RATE_LIMIT:
                await asyncio.sleep(TRANSLATION_RATE_LIMIT - elapsed)
            self._last_api_call_time = time.time()

            for chunk in chunks:
                trans_chunk, chunk_lang = await self._translate_chunk(chunk, target_lang)
                translated_chunks.append(trans_chunk)
                if chunk_lang and chunk_lang != "auto":
                    detected_lang = chunk_lang

        translated_raw = "\n".join(translated_chunks)

        # If all translation engines failed, return original text safely
        if not translated_raw or self._is_invalid_translation(translated_raw):
            logger.error("All translation providers failed to translate post. Falling back to original text.")
            return self._wrap_fallback_error(html_text), "auto", False

        # 5. Check if source text was already in target language (e.g. English to English)
        if detected_lang == target_lang or translated_raw.strip() == protected_text.strip():
            logger.debug(f"Source text is already in target language ({target_lang}). Skipping translation.")
            await db.set_cached_translation(text_hash, detected_lang, html_text)
            return html_text, detected_lang, False

        # 6. Re-stitch original formatting and placeholders
        translated_html = self._restore_placeholders(translated_raw, placeholders)
        if self._is_invalid_translation(translated_html):
            logger.error("Restored translated HTML contained error signature. Falling back to original text.")
            return self._wrap_fallback_error(html_text), detected_lang, False

        # 7. Update caches
        self._memory_cache[cache_key] = translated_html
        await db.set_cached_translation(text_hash, detected_lang, translated_html)

        return translated_html, detected_lang, True

    def _wrap_fallback_error(self, text: str) -> str:
        """Wraps text in a gentle visual indicator that translation failed, keeping bot crash-free."""
        return f"{text}\n\n<i>⚠️ [Translation Unavailable - Displaying Original]</i>"

# Singleton Translation Service
translation_service = TranslationService()


