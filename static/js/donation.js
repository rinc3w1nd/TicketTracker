(function () {
  const logoButton = document.getElementById('brand-logo-button');
  const modal = document.getElementById('donation-modal');

  if (!logoButton || !modal) {
    return;
  }

  const closeButton = modal.querySelector('.donation-modal__close');
  const backdrop = modal.querySelector('.donation-modal__backdrop');
  const dialog = modal.querySelector('.donation-modal__dialog');
  const focusableSelector =
    'a[href], area[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

  let previousActiveElement = null;

  function getFocusableElements() {
    return Array.from(modal.querySelectorAll(focusableSelector)).filter(function (element) {
      if (element.hasAttribute('hidden') || element.getAttribute('aria-hidden') === 'true') {
        return false;
      }
      return typeof element.focus === 'function';
    });
  }

  function openModal() {
    previousActiveElement = document.activeElement;
    modal.removeAttribute('hidden');
    document.body.classList.add('donation-modal-open');
    logoButton.setAttribute('aria-expanded', 'true');

    window.requestAnimationFrame(function () {
      if (closeButton) {
        closeButton.focus();
        return;
      }

      if (dialog && typeof dialog.focus === 'function') {
        dialog.focus({ preventScroll: true });
      }
    });

    document.addEventListener('keydown', handleKeyDown);
  }

  function closeModal() {
    modal.setAttribute('hidden', '');
    document.body.classList.remove('donation-modal-open');
    logoButton.setAttribute('aria-expanded', 'false');
    document.removeEventListener('keydown', handleKeyDown);

    if (
      previousActiveElement &&
      typeof previousActiveElement.focus === 'function' &&
      document.contains(previousActiveElement)
    ) {
      previousActiveElement.focus();
    } else {
      logoButton.focus();
    }
  }

  function handleKeyDown(event) {
    if (modal.hasAttribute('hidden')) {
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      closeModal();
      return;
    }

    if (event.key !== 'Tab') {
      return;
    }

    const focusable = getFocusableElements();
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (event.shiftKey) {
      if (active === first || !modal.contains(active)) {
        event.preventDefault();
        last.focus();
      }
    } else if (active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  logoButton.addEventListener('click', function () {
    if (modal.hasAttribute('hidden')) {
      openModal();
    } else {
      closeModal();
    }
  });

  if (closeButton) {
    closeButton.addEventListener('click', function () {
      closeModal();
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', function () {
      closeModal();
    });
  }

  modal.addEventListener('click', function (event) {
    if (event.target && event.target.dataset && event.target.dataset.close === 'donation-modal') {
      closeModal();
    }
  });
})();
