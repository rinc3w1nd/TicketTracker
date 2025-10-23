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
    this.pointerTracking = false;
    this.pointerPosition = null;
    this.pointerStationaryTimeout = null;
    this.openedByPointer = false;
    this.activePointerId = null;

    this.onPointerMove = this.onPointerMove.bind(this);

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

  open({ focusSurface = false, positionStrategy = null } = {}) {
    if (this.active) {
      if (typeof positionStrategy === 'function') {
        positionStrategy();
      }
      return;
    }
    this.active = true;
    if (this.hideTimeout) {
      window.clearTimeout(this.hideTimeout);
      this.hideTimeout = null;
    }
    this.tooltip.hidden = false;
    if (typeof positionStrategy === 'function') {
      positionStrategy();
    }
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
    this.stopPointerTracking();
    this.openedByPointer = false;
    this.pointerPosition = null;
    this.activePointerId = null;
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

  onTriggerPointerEnter(event) {
    this.hovering = true;
    this.startPointerTracking(event);
  }

  onTriggerPointerLeave(event) {
    if (this.containsWithin(event.relatedTarget)) {
      return;
    }
    this.hovering = false;
    this.stopPointerTracking();
    if (!this.focusWithin) {
      this.close();
    }
  }

  onTooltipPointerEnter(event) {
    this.hovering = true;
    this.startPointerTracking(event);
  }

  onTooltipPointerLeave(event) {
    if (this.containsWithin(event.relatedTarget)) {
      return;
    }
    this.hovering = false;
    this.stopPointerTracking();
    if (!this.focusWithin) {
      this.close();
    }
  }

  onFocusIn(event) {
    if (!this.containsWithin(event.target)) {
      return;
    }
    this.focusWithin = true;
    if (this.active) {
      return;
    }
    this.openedByPointer = false;
    this.pointerPosition = null;
    this.clearPointerStationaryTimer();
    this.open({
      focusSurface: this.tooltip === event.target,
      positionStrategy: () => this.updatePositionFromTrigger(),
    });
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

  startPointerTracking(event) {
    if (event && typeof event.pointerId === 'number') {
      this.activePointerId = event.pointerId;
    }
    if (!this.hovering) {
      return;
    }
    if (event) {
      this.pointerPosition = {
        x: event.clientX,
        y: event.clientY,
      };
    }
    if (!this.pointerTracking) {
      document.addEventListener('pointermove', this.onPointerMove);
      this.pointerTracking = true;
    }
    this.restartPointerStationaryTimer();
  }

  stopPointerTracking() {
    if (!this.pointerTracking) {
      return;
    }
    document.removeEventListener('pointermove', this.onPointerMove);
    this.pointerTracking = false;
    this.activePointerId = null;
    this.clearPointerStationaryTimer();
  }

  onPointerMove(event) {
    if (this.activePointerId !== null && event.pointerId !== this.activePointerId) {
      return;
    }
    if (!this.hovering) {
      return;
    }
    this.pointerPosition = {
      x: event.clientX,
      y: event.clientY,
    };
    this.restartPointerStationaryTimer();
  }

  restartPointerStationaryTimer() {
    this.clearPointerStationaryTimer();
    this.pointerStationaryTimeout = window.setTimeout(() => this.handlePointerStationary(), 1000);
  }

  clearPointerStationaryTimer() {
    if (this.pointerStationaryTimeout) {
      window.clearTimeout(this.pointerStationaryTimeout);
      this.pointerStationaryTimeout = null;
    }
  }

  handlePointerStationary() {
    this.pointerStationaryTimeout = null;
    if (!this.hovering) {
      return;
    }
    if (!this.pointerPosition) {
      if (this.active) {
        this.updatePositionFromTrigger();
        return;
      }
      this.openedByPointer = false;
      this.open({ positionStrategy: () => this.updatePositionFromTrigger() });
      return;
    }
    if (this.active) {
      this.openedByPointer = true;
      this.updatePositionFromPointer();
      return;
    }
    this.openedByPointer = true;
    this.open({ positionStrategy: () => this.updatePositionFromPointer() });
  }

  updatePositionFromPointer() {
    if (!this.pointerPosition) {
      this.updatePositionFromTrigger();
      return;
    }
    const margin = 8;
    const offset = 16;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const rect = this.tooltip.getBoundingClientRect();
    const tooltipWidth = rect.width;
    const tooltipHeight = rect.height;
    const pointerX = this.pointerPosition.x;
    const pointerY = this.pointerPosition.y;

    let left;
    const fitsRight = pointerX + offset + tooltipWidth + margin <= viewportWidth;
    if (fitsRight) {
      left = Math.max(pointerX + offset, margin);
    } else {
      left = pointerX - offset - tooltipWidth;
      if (left < margin) {
        left = margin;
      }
      if (left + tooltipWidth + margin > viewportWidth) {
        left = Math.max(margin, viewportWidth - tooltipWidth - margin);
      }
    }

    let top = pointerY - tooltipHeight / 2;
    if (top < margin) {
      top = margin;
    }
    if (top + tooltipHeight + margin > viewportHeight) {
      top = Math.max(margin, viewportHeight - tooltipHeight - margin);
    }

    this.tooltip.style.top = `${top}px`;
    this.tooltip.style.left = `${left}px`;
  }

  updatePositionFromTrigger() {
    const margin = 8;
    const offset = 16;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const triggerRect = this.trigger.getBoundingClientRect();
    const tooltipRect = this.tooltip.getBoundingClientRect();
    const tooltipWidth = tooltipRect.width;
    const tooltipHeight = tooltipRect.height;

    let left = triggerRect.left + triggerRect.width / 2 - tooltipWidth / 2;
    if (left < margin) {
      left = margin;
    }
    if (left + tooltipWidth + margin > viewportWidth) {
      left = Math.max(margin, viewportWidth - tooltipWidth - margin);
    }

    let top = triggerRect.bottom + offset;
    if (top + tooltipHeight + margin > viewportHeight) {
      const above = triggerRect.top - offset - tooltipHeight;
      if (above >= margin) {
        top = above;
      } else {
        top = Math.max(margin, viewportHeight - tooltipHeight - margin);
      }
    }

    this.tooltip.style.top = `${top}px`;
    this.tooltip.style.left = `${left}px`;
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
