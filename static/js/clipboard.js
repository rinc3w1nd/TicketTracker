const buttons = document.querySelectorAll('[data-clipboard-button]');

if (buttons.length) {
  const resetTimers = new WeakMap();
  const canWriteAdvanced =
    typeof window.ClipboardItem !== 'undefined' &&
    navigator.clipboard &&
    typeof navigator.clipboard.write === 'function';
  const canWriteText =
    navigator.clipboard && typeof navigator.clipboard.writeText === 'function';

  const clearStatusLater = (button, statusEl) => {
    const existing = resetTimers.get(button);
    if (existing) {
      window.clearTimeout(existing);
    }
    const timer = window.setTimeout(() => {
      if (statusEl) {
        statusEl.textContent = '';
      }
      button.classList.remove('is-success', 'is-error', 'is-warning');
      resetTimers.delete(button);
    }, 2400);
    resetTimers.set(button, timer);
  };

  const setStatus = (button, statusEl, message, state) => {
    if (statusEl) {
      statusEl.textContent = message;
    }
    button.classList.remove('is-success', 'is-error', 'is-warning');
    if (state) {
      button.classList.add(`is-${state}`);
      clearStatusLater(button, statusEl);
    }
  };

  const hideFallback = (fallbackEl) => {
    if (!fallbackEl) {
      return;
    }
    if (!fallbackEl.hidden) {
      fallbackEl.hidden = true;
      const textarea = fallbackEl.querySelector('[data-clipboard-textarea]');
      if (textarea) {
        textarea.blur();
      }
    }
  };

  const legacyCopy = (text) => {
    if (!text || typeof document.execCommand !== 'function') {
      return false;
    }
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    let success = false;
    try {
      success = document.execCommand('copy');
    } catch (error) {
      success = false;
    }
    textarea.remove();
    return success;
  };

  const showFallback = (fallbackEl, text) => {
    if (!fallbackEl) {
      return false;
    }
    const textarea = fallbackEl.querySelector('[data-clipboard-textarea]');
    if (!textarea) {
      return false;
    }
    fallbackEl.hidden = false;
    textarea.value = text;
    textarea.focus();
    textarea.select();
    fallbackEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    return true;
  };

  const copyAdvanced = async (html, text) => {
    const payload = {};
    if (html) {
      payload['text/html'] = new Blob([html], { type: 'text/html' });
    }
    payload['text/plain'] = new Blob([text], { type: 'text/plain' });
    await navigator.clipboard.write([new ClipboardItem(payload)]);
  };

  buttons.forEach((button) => {
    button.addEventListener('click', async () => {
      const container = button.closest('[data-clipboard-container]');
      if (!container) {
        return;
      }

      const statusEl = container.querySelector('[data-clipboard-status]');
      const fallbackEl = container.querySelector('[data-clipboard-fallback]');
      const htmlTemplate = container.querySelector('[data-clipboard-html]');
      const textTemplate = container.querySelector('[data-clipboard-text]');

      const htmlContent = htmlTemplate ? htmlTemplate.innerHTML.trim() : '';
      const htmlTextFallback = htmlTemplate
        ? htmlTemplate.content.textContent.trim()
        : '';
      const textContent = textTemplate
        ? textTemplate.content.textContent.trim()
        : '';

      const fallbackText = textContent || htmlTextFallback || '';

      if (!fallbackText && !htmlContent) {
        setStatus(button, statusEl, 'Nothing to copy yet.', 'error');
        return;
      }

      try {
        if (canWriteAdvanced) {
          await copyAdvanced(htmlContent, fallbackText);
          hideFallback(fallbackEl);
          setStatus(button, statusEl, 'Summary copied.', 'success');
          return;
        }
      } catch (error) {
        console.warn('Advanced clipboard copy failed', error);
      }

      if (canWriteText && fallbackText) {
        try {
          await navigator.clipboard.writeText(fallbackText);
          hideFallback(fallbackEl);
          setStatus(button, statusEl, 'Summary copied.', 'success');
          return;
        } catch (error) {
          console.warn('Clipboard writeText failed', error);
        }
      }

      if (legacyCopy(fallbackText)) {
        hideFallback(fallbackEl);
        setStatus(button, statusEl, 'Summary copied.', 'success');
        return;
      }

      if (showFallback(fallbackEl, fallbackText)) {
        setStatus(
          button,
          statusEl,
          'Clipboard unavailable. Text selected below.',
          'warning',
        );
        return;
      }

      setStatus(button, statusEl, 'Clipboard unavailable.', 'error');
    });
  });
}
