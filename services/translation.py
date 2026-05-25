import asyncio
import hashlib
import re
import time
from typing import Dict, Tuple, List, Optional
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

    async def detect_language(self, text: str) -> str:
        """Detects the language of the clean text, defaulting to 'en' on failure."""
        # Strip placeholders and HTML-like tags for cleaner detection
        clean_text = re.sub(r"<[^>]+>", "", text)
        clean_text = re.sub(r"#\w+", "", clean_text)
        clean_text = re.sub(r"https?://[^\s<>]+", "", clean_text).strip()

        # If too short or mostly numbers/emojis, assume English to avoid errors
        if not clean_text or len(re.sub(r"[^\w]", "", clean_text)) < 3:
            return "en"

        try:
            # Run blocking detection in thread pool
            lang = await asyncio.to_thread(detect, clean_text)
            return lang
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
            logger.debug("Translation found in memory cache.")
            return self._memory_cache[cache_key], "auto", True

        # 2. Check Database Cache
        db_cache = await db.get_cached_translation(text_hash)
        if db_cache:
            source_lang, translated_text = db_cache
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

        # 5. External API translation (with Rate-Limiting & Thread Pool)
        translated_raw = ""
        try:
            async with self._api_call_lock:
                # Enforce minimal request interval to avoid Google Translate rate limits
                now = time.time()
                elapsed = now - self._last_api_call_time
                if elapsed < TRANSLATION_RATE_LIMIT:
                    sleep_time = TRANSLATION_RATE_LIMIT - elapsed
                    logger.debug(f"Rate limiter: sleeping for {sleep_time:.2f}s...")
                    await asyncio.sleep(sleep_time)

                self._last_api_call_time = time.time()

                # Execute blocking translation inside threadpool
                translator = GoogleTranslator(source="auto", target=target_lang)
                translated_raw = await asyncio.to_thread(translator.translate, protected_text)

        except BaseError as e:
            logger.error(f"Google Translator API Error: {e}")
            # Fallback gracefully
            return self._wrap_fallback_error(html_text), detected_lang, False
        except Exception as e:
            logger.error(f"Unexpected translation error: {e}", exc_info=True)
            # Fallback gracefully
            return self._wrap_fallback_error(html_text), detected_lang, False

        if not translated_raw:
            return self._wrap_fallback_error(html_text), detected_lang, False

        # 6. Re-stitch original formatting
        translated_html = self._restore_placeholders(translated_raw, placeholders)

        # 7. Update caches
        self._memory_cache[cache_key] = translated_html
        await db.set_cached_translation(text_hash, detected_lang, translated_html)

        return translated_html, detected_lang, True

    def _wrap_fallback_error(self, text: str) -> str:
        """Wraps text in a gentle visual indicator that translation failed, keeping bot crash-free."""
        # Retain original text and append warning footer in markdown/HTML
        return f"{text}\n\n<i>⚠️ [Translation Unavailable - Displaying Original]</i>"

# Singleton Translation Service
translation_service = TranslationService()
