class TicketTooltipController {
  constructor(trigger, tooltip) {
    this.trigger = trigger;
    this.tooltip = tooltip;
    this.surface = tooltip.querySelector('[data-tooltip-surface]') || tooltip;
    this.closeButton = tooltip.querySelector('[data-tooltip-close]');
    this.hideTimeout = null;
    this.active = false;
    this.hovering = false;
    this.focusWithin = false;

    this.onTriggerPointerEnter = this.onTriggerPointerEnter.bind(this);
    this.onTriggerPointerLeave = this.onTriggerPointerLeave.bind(this);
    this.onTooltipPointerEnter = this.onTooltipPointerEnter.bind(this);
    this.onTooltipPointerLeave = this.onTooltipPointerLeave.bind(this);
    this.onFocusIn = this.onFocusIn.bind(this);
    this.onFocusOut = this.onFocusOut.bind(this);
    this.onKeyDown = this.onKeyDown.bind(this);

    trigger.addEventListener('pointerenter', this.onTriggerPointerEnter);
    trigger.addEventListener('pointerleave', this.onTriggerPointerLeave);
    trigger.addEventListener('focusin', this.onFocusIn);
    trigger.addEventListener('focusout', this.onFocusOut);
    trigger.addEventListener('keydown', this.onKeyDown);

    tooltip.addEventListener('pointerenter', this.onTooltipPointerEnter);
    tooltip.addEventListener('pointerleave', this.onTooltipPointerLeave);
    tooltip.addEventListener('focusin', this.onFocusIn);
    tooltip.addEventListener('focusout', this.onFocusOut);
    tooltip.addEventListener('keydown', this.onKeyDown);

    if (this.closeButton) {
      this.closeButton.addEventListener('click', () => this.close({ returnFocus: true }));
    }

    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-haspopup', 'dialog');
  }

  open({ focusSurface = false } = {}) {
    if (this.active) {
      return;
    }
    this.active = true;
    if (this.hideTimeout) {
      window.clearTimeout(this.hideTimeout);
      this.hideTimeout = null;
    }
    this.tooltip.hidden = false;
    requestAnimationFrame(() => {
      this.tooltip.classList.add('is-visible');
    });
    this.tooltip.setAttribute('aria-hidden', 'false');
    this.trigger.setAttribute('aria-expanded', 'true');
    if (focusSurface && this.surface) {
      this.surface.focus({ preventScroll: true });
    }
  }

  close({ returnFocus = false } = {}) {
    if (!this.active) {
      return;
    }
    this.active = false;
    this.tooltip.classList.remove('is-visible');
    this.tooltip.setAttribute('aria-hidden', 'true');
    this.trigger.setAttribute('aria-expanded', 'false');
    this.hovering = false;
    this.focusWithin = false;
    if (this.hideTimeout) {
      window.clearTimeout(this.hideTimeout);
    }
    this.hideTimeout = window.setTimeout(() => {
      this.tooltip.hidden = true;
      this.hideTimeout = null;
    }, 180);
    if (returnFocus) {
      this.trigger.focus({ preventScroll: true });
    }
  }

  containsWithin(node) {
    if (!node) {
      return false;
    }
    return this.trigger.contains(node) || this.tooltip.contains(node);
  }

  onTriggerPointerEnter() {
    this.hovering = true;
    this.open();
  }

  onTriggerPointerLeave(event) {
    if (this.containsWithin(event.relatedTarget)) {
      return;
    }
    this.hovering = false;
    if (!this.focusWithin) {
      this.close();
    }
  }

  onTooltipPointerEnter() {
    this.hovering = true;
  }

  onTooltipPointerLeave(event) {
    if (this.containsWithin(event.relatedTarget)) {
      return;
    }
    this.hovering = false;
    if (!this.focusWithin) {
      this.close();
    }
  }

  onFocusIn(event) {
    if (!this.containsWithin(event.target)) {
      return;
    }
    this.focusWithin = true;
    this.open({ focusSurface: this.tooltip === event.target });
  }

  onFocusOut(event) {
    if (this.containsWithin(event.relatedTarget)) {
      return;
    }
    this.focusWithin = false;
    if (!this.hovering) {
      this.close();
    }
  }

  onKeyDown(event) {
    if (event.key === 'Escape' || event.key === 'Esc') {
      if (!this.active) {
        return;
      }
      event.preventDefault();
      this.close({ returnFocus: true });
      return;
    }

    if (event.key !== 'Tab' || !this.active) {
      return;
    }

    const focusables = this.getFocusableElements();
    if (focusables.length === 0) {
      event.preventDefault();
      return;
    }

    const current = document.activeElement;
    if (!this.tooltip.contains(current)) {
      return;
    }

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (event.shiftKey) {
      if (current === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      }
    } else if (current === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  }

  getFocusableElements() {
    const selectors = [
      'a[href]:not([tabindex="-1"])',
      'button:not([disabled]):not([tabindex="-1"])',
      'textarea:not([disabled]):not([tabindex="-1"])',
      'input:not([disabled]):not([tabindex="-1"])',
      'select:not([disabled]):not([tabindex="-1"])',
      '[tabindex]:not([tabindex="-1"])',
    ];
    return Array.from(this.tooltip.querySelectorAll(selectors.join(',')));
  }
}

function initializeTicketTooltips() {
  const triggers = document.querySelectorAll('[data-ticket-tooltip-trigger]');
  triggers.forEach((trigger) => {
    const tooltipId = trigger.getAttribute('data-tooltip-id');
    if (!tooltipId) {
      return;
    }
    const tooltip = document.getElementById(tooltipId);
    if (!tooltip) {
      return;
    }
    if (!tooltip.hasAttribute('data-ticket-tooltip')) {
      return;
    }
    new TicketTooltipController(trigger, tooltip);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeTicketTooltips);
} else {
  initializeTicketTooltips();
}
