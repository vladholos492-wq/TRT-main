"""
Centralized UX copy layer for Russian language.

All user-facing texts are stored here to ensure consistency and easy updates.
No business logic, only copy.
"""
from typing import Dict, Any, Optional


# Main copy dictionary
COPY: Dict[str, str] = {
    # Main menu / Welcome
    "welcome_title": "👋 Добро пожаловать, {name}!",
    "welcome_subtitle": "Креативы за 60 секунд",
    "welcome_description": (
        "Профессиональная платформа для генерации контента.\n"
        "Создавай изображения, видео, аудио — быстро и качественно."
    ),
    "welcome_benefit": (
        "✨ {count}+ AI-моделей от ведущих разработчиков\n"
        "⚡ Мгновенная генерация • 🎯 Высокое качество"
    ),
    "welcome_hint": "Сначала выбери тип, дальше мастер сам спросит всё нужное.",
    "main_menu_title": "🏠 Главное меню",
    "main_menu_subtitle": (
        "✨ {count}+ AI-моделей премиум-класса\n\n"
        "🎨 <b>Категории:</b> Картинки, Видео, Аудио, Улучшение\n"
        "🔥 <b>Trending:</b> самые популярные модели"
    ),
    
    # Category benefits (for each category screen)
    "category_image_benefit": "Для рекламы, карточек WB, обложек, сторис/рилс",
    "category_video_benefit": "Для рекламы, сторис, рилс, постов",
    "category_audio_benefit": "Для озвучки, подкастов, музыки",
    "category_enhance_benefit": "Для улучшения качества, апскейла",
    "category_avatar_benefit": "Для аватарок, баннеров, персонажей",
    "category_music_benefit": "Для музыки, саундтреков, фонов",
    
    # Model badges (static, computed from model_id)
    "badge_realistic": "Самая реалистичная",
    "badge_fast": "Быстрая",
    "badge_top_ad": "Топ для рекламы",
    "badge_cinematic": "Киношный стиль",
    "badge_premium": "Премиум",
    "badge_popular": "Популярная",
    
    # Input master - Step prompts
    "step_prompt_title": "Шаг {current}/{total} — Что делаем?",
    "step_prompt_explanation": (
        "Опиши результат простыми словами. Можно без 'промпт-магии'."
    ),
    "step_prompt_examples": (
        "<b>Примеры:</b>\n"
        "• Баннер для Telegram: нейросети для креативов, стиль премиум\n"
        "• Обложка для ВК: минимализм, крупный объект, контраст\n"
        "• Реклама подписки: акцент на скорости и выгоде"
    ),
    "step_prompt_limits": "до {max} символов, без ссылок/телефонов, без капса",
    "step_prompt_next": "Следом выберем формат и подтвердим.",
    
    "step_ratio_title": "Шаг {current}/{total} — Формат",
    "step_ratio_explanation": (
        "Выбери соотношение сторон для результата:\n\n"
        "• <b>9:16</b> — для сторис, рилс, вертикальные посты\n"
        "• <b>1:1</b> — для постов в соцсетях, квадрат\n"
        "• <b>16:9</b> — для видео, горизонтальные баннеры\n"
        "• <b>4:3</b> — классический формат"
    ),
    "step_ratio_next": "После выбора формата — финальное подтверждение.",
    
    "step_confirm_title": "Шаг {current}/{total} — Проверяем перед запуском",
    "step_confirm_summary": (
        "<b>Задача:</b> {prompt}\n"
        "<b>Формат:</b> {ratio}\n"
        "<b>Модель:</b> {model}"
    ),
    "step_confirm_hint": "Всё верно? Нажми 'Запустить' для генерации.",
    
    # Category selection micro-moment
    "category_selected_message": (
        "Сейчас соберём креатив как в агентстве: быстро, понятно, без лишнего."
    ),
    
    # After confirmation (success)
    "generation_started": (
        "✅ Готово. Следующий шаг: сохранить шаблон / сделать ещё один вариант."
    ),
    "generation_hint": (
        "💡 Хочешь 3 варианта — просто напиши 'сделай ещё 2'"
    ),
    
    # DRY_RUN notice
    "dry_run_notice": (
        "🔧 <b>Демо-режим</b>\n\n"
        "Генерация имитируется, чтобы всё было без риска и без списаний.\n"
        "Job ID: <code>{job_id}</code>\n\n"
        "В реальном режиме здесь будет ссылка на результат."
    ),
    
    # Errors (human-friendly)
    "error_generic": (
        "Похоже, не понял ввод. Дай 1 фразу: что на картинке и для чего."
    ),
    "error_too_long": "Слишком длинный текст. Максимум {max} символов.",
    "error_invalid_format": "Неверный формат. Проверь и попробуй ещё раз.",
    "error_required_field": "Это поле обязательно. Пожалуйста, заполни его.",
    
    # Buttons (keep existing callback_data)
    "button_back": "◀️ Назад",
    "button_cancel": "❌ Отмена",
    "button_confirm": "✅ Запустить",
    "button_edit_prompt": "✏️ Изменить описание",
    "button_main_menu": "🏠 В меню",
    
    # Help / Support
    "help_title": "❓ Помощь",
    "help_text": (
        "Выберите вопрос:\n\n"
        "• Как получить бесплатные генерации?\n"
        "• Как пополнить баланс?\n"
        "• Как работает ценообразование?\n"
        "• Что делать при ошибке?"
    ),
    
    # Balance
    "balance_title": "💰 Баланс",
    "balance_amount": "Текущий баланс: <b>{amount}₽</b>",
    "balance_topup_hint": "Пополнить баланс можно через меню ниже.",
}


def t(key: str, **kwargs: Any) -> str:
    """
    Get localized text with safe formatting.
    
    Args:
        key: Copy key from COPY dictionary
        **kwargs: Format arguments (e.g., name="Иван", count=100)
    
    Returns:
        Formatted string, or key if not found (fail-safe)
    """
    text = COPY.get(key, key)  # Return key if not found (fail-safe)
    
    try:
        return text.format(**kwargs)
    except (KeyError, ValueError):
        # If formatting fails, return text as-is
        return text


def get_category_benefit(category: str) -> str:
    """Get benefit line for category."""
    benefit_key = f"category_{category}_benefit"
    return COPY.get(benefit_key, "")


def get_model_badge(model_id: str) -> Optional[str]:
    """
    Get static badge for model (computed from model_id).
    
    This is a simple heuristic - can be extended with actual model registry.
    """
    model_lower = model_id.lower()
    
    # Simple heuristics (can be extended)
    if "realistic" in model_lower or "photorealistic" in model_lower:
        return COPY["badge_realistic"]
    if "fast" in model_lower or "turbo" in model_lower:
        return COPY["badge_fast"]
    if "cinematic" in model_lower or "film" in model_lower:
        return COPY["badge_cinematic"]
    if "premium" in model_lower or "pro" in model_lower:
        return COPY["badge_premium"]
    
    # Default: popular badge for well-known models
    known_models = ["flux", "veo", "midjourney", "dalle", "stable-diffusion"]
    if any(known in model_lower for known in known_models):
        return COPY["badge_popular"]
    
    return None


__all__ = ["COPY", "t", "get_category_benefit", "get_model_badge"]

