import asyncio
import hashlib
import re
import time
from typing import Dict, Tuple, List, Optional
from deep_translator import GoogleTranslator
from deep_translator.exceptions import BaseError
from langdetect import detect, detect_langs, LangDetectException

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

    def _extract_placeholders(self, html_text: str) -> Tuple[str, List[str]]:
        """
        Extracts HTML tags, hashtags, and raw URLs, replacing them with placeholders
        to preserve them exactly during translation.
        """
        placeholders = []
        temp_text = html_text

        # 1. Protect HTML Tags (e.g. <a href="...">, <b>, </i>, etc.)
        def tag_replacer(match):
            placeholders.append(match.group(0))
            return f"{{{{T_{len(placeholders) - 1}}}}}"
        temp_text = re.sub(r"<[^>]+>", tag_replacer, temp_text)

        # 2. Protect raw URLs that aren't inside HTML tags already
        # (matching http/https links not surrounded by curly braces placeholder characters)
        def url_replacer(match):
            placeholders.append(match.group(0))
            return f"{{{{U_{len(placeholders) - 1}}}}}"
        # Matches typical URLs
        temp_text = re.sub(r"(?<!\{)https?://[^\s<>]+(?!})", url_replacer, temp_text)

        # 3. Protect Hashtags
        def hashtag_replacer(match):
            placeholders.append(match.group(0))
            return f"{{{{H_{len(placeholders) - 1}}}}}"
        temp_text = re.sub(r"(?<!\w)#\w+", hashtag_replacer, temp_text)

        return temp_text, placeholders

    def _restore_placeholders(self, translated_text: str, placeholders: List[str]) -> str:
        """Restores the original HTML tags, hashtags, and URLs back into the translated text."""
        restored = translated_text
        for i, val in enumerate(placeholders):
            # Try to match both standard and slightly deformed placeholders
            # (sometimes translator adds spaces, e.g. {{ T_0 }} or {{t_0}})
            pattern = re.compile(r"\{\{\s*[TUH]_" + str(i) + r"\s*\}\}", re.IGNORECASE)
            
            # If not found with braces, try to fallback to the literal placeholder
            if pattern.search(restored):
                restored = pattern.sub(val, restored, count=1)
            else:
                # If Google Translator removed/corrupted the curly braces, try a direct string replace
                raw_placeholder_pattern = r"\{\{\s*[TUH]_" + str(i) + r"\s*\}\}"
                restored = re.sub(raw_placeholder_pattern, val, restored, flags=re.IGNORECASE)
        
        # Clean up any leftover double spaces around tags/hashtags that Google Translator might introduce
        restored = re.sub(r"\s*\{\{\s*([TUH]_\d+)\s*\}\}\s*", r" {{\1}} ", restored)
        # Put back correct spaces
        for i, val in enumerate(placeholders):
            restored = restored.replace(f"{{{{T_{i}}}}}", val)
            restored = restored.replace(f"{{{{U_{i}}}}}", val)
            restored = restored.replace(f"{{{{H_{i}}}}}", val)

        # Remove duplicate spaces
        restored = re.sub(r" +", " ", restored).strip()
        return restored

    def _is_invalid_translation(self, text: str) -> bool:
        """
        Checks if the translator returned a scraped HTTP error page or error message
        instead of actual translated text.
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
            "<title>error"
        ]
        
        for indicator in error_indicators:
            if indicator in lowered:
                return True
                
        return False

    async def detect_language(self, text: str) -> str:
        """
        Detects the language of the clean text, defaulting to 'en' on failure.
        Supports mixed posts (e.g. English header/title followed by a non-English body)
        by inspecting lines, script ranges, and probability distributions.
        """
        # Strip placeholders and HTML-like tags for cleaner detection
        clean_text = re.sub(r"<[^>]+>", "", text)
        clean_text = re.sub(r"#\w+", "", clean_text)
        clean_text = re.sub(r"https?://[^\s<>]+", "", clean_text).strip()

        # If too short or mostly numbers/emojis, assume English to avoid errors
        if not clean_text or len(re.sub(r"[^\w]", "", clean_text)) < 3:
            return "en"

        # 1. Direct Script Range Check (Cyrillic, Devanagari, Arabic, CJK)
        if re.search(r"[\u0400-\u04FF]", clean_text):
            return "ru"
        if re.search(r"[\u0900-\u097F]", clean_text):
            return "hi"
        if re.search(r"[\u0600-\u06FF]", clean_text):
            return "ar"
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", clean_text):
            return "zh"

        # 2. Line-by-line inspection for mixed posts (e.g. EN title + ES/FR/IT body)
        lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
        for line in lines:
            words = re.sub(r"[^\w\s]", "", line).strip()
            if len(words.split()) >= 3:
                try:
                    lang = await asyncio.to_thread(detect, line)
                    if lang != "en":
                        return lang
                except Exception:
                    continue

        # 3. Probabilistic check with detect_langs
        try:
            predictions = await asyncio.to_thread(detect_langs, clean_text)
            for p in predictions:
                if p.lang != "en" and p.prob > 0.08:
                    return p.lang
        except Exception:
            pass

        # 4. Fallback to overall detect
        try:
            return await asyncio.to_thread(detect, clean_text)
        except LangDetectException:
            return "en"
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
            return "en"

    async def translate_html(
        self, html_text: str, target_lang: str = DEFAULT_TARGET_LANGUAGE
    ) -> Tuple[str, str, bool]:
        """
        Translates HTML text/caption to target language (e.g. 'en') while preserving formatting.
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

        # 3. Detect Language to skip translation if already in target language
        detected_lang = await self.detect_language(html_text)
        if detected_lang == target_lang:
            logger.debug(f"Source text is already in target language ({target_lang}). Skipping translation.")
            # Cache the original text in DB to skip future lookups
            await db.set_cached_translation(text_hash, detected_lang, html_text)
            return html_text, detected_lang, False

        # 4. Protect formatting/tags/links
        protected_text, placeholders = self._extract_placeholders(html_text)
        
        # If there are no alphabetical words to translate after stripping placeholders, skip
        words_only = re.sub(r"\{\{[TUH]_\d+\}\}", "", protected_text)
        if not re.sub(r"[^\w]", "", words_only).strip():
            return html_text, detected_lang, False

        # 5. External API translation (with Rate-Limiting, Retries & Fast Failover Provider)
        translated_raw = ""
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                async with self._api_call_lock:
                    now = time.time()
                    elapsed = now - self._last_api_call_time
                    if elapsed < TRANSLATION_RATE_LIMIT:
                        sleep_time = TRANSLATION_RATE_LIMIT - elapsed
                        await asyncio.sleep(sleep_time)

                    self._last_api_call_time = time.time()

                    # Execute primary GoogleTranslator
                    translator = GoogleTranslator(source="auto", target=target_lang)
                    res = await asyncio.to_thread(translator.translate, protected_text)
                    
                    if res and not self._is_invalid_translation(res):
                        translated_raw = res
                        break
                    else:
                        logger.warning(
                            f"Google Translator returned invalid/error response (attempt {attempt+1}/{max_attempts}). Trying failover provider..."
                        )
            except BaseError as e:
                logger.error(f"Google Translator API Error (attempt {attempt+1}/{max_attempts}): {e}")
            except Exception as e:
                logger.error(f"Unexpected translation error (attempt {attempt+1}/{max_attempts}): {e}")

            # Instant Failover to MyMemory API if Google failed/rate-limited
            logger.info("Attempting instant secondary API failover (MyMemory)...")
            failover_res = await self._translate_mymemory(protected_text, detected_lang, target_lang)
            if failover_res and not self._is_invalid_translation(failover_res):
                logger.info("Failover translation succeeded via MyMemory.")
                translated_raw = failover_res
                break

            if attempt < max_attempts - 1:
                await asyncio.sleep(0.3)

        if not translated_raw or self._is_invalid_translation(translated_raw):
            logger.error("All translation providers failed. Falling back to original text.")
            return self._wrap_fallback_error(html_text), detected_lang, False

        # 6. Re-stitch original formatting
        translated_html = self._restore_placeholders(translated_raw, placeholders)
        if self._is_invalid_translation(translated_html):
            logger.error("Restored translated HTML contained error signature. Falling back to original text.")
            return self._wrap_fallback_error(html_text), detected_lang, False

        # 7. Update caches
        self._memory_cache[cache_key] = translated_html
        await db.set_cached_translation(text_hash, detected_lang, translated_html)

        return translated_html, detected_lang, True

    async def _translate_mymemory(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        """Secondary fast failover translator using MyMemory API (free, fast, no scraping required)."""
        try:
            import urllib.parse
            import httpx
            src = source_lang if source_lang and source_lang != 'auto' else 'autodetect'
            langpair = f"{src}|{target_lang}"
            url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair={langpair}"
            
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    translated = data.get("responseData", {}).get("translatedText")
                    if translated and not self._is_invalid_translation(translated):
                        # Clean up HTML tags if MyMemory wrapped result in <p>...</p>
                        clean_res = re.sub(r"^<p>|</p>$", "", translated.strip(), flags=re.IGNORECASE)
                        return clean_res
        except Exception as e:
            logger.warning(f"MyMemory failover translation failed: {e}")
        return None

    def _wrap_fallback_error(self, text: str) -> str:
        """Wraps text in a gentle visual indicator that translation failed, keeping bot crash-free."""
        # Retain original text and append warning footer in markdown/HTML
        return f"{text}\n\n<i>⚠️ [Translation Unavailable - Displaying Original]</i>"

# Singleton Translation Service
translation_service = TranslationService()
