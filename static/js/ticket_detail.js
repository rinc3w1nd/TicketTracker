const quickAttachTrigger = document.querySelector('[data-quick-attachment-trigger]');
const quickAttachInput = document.querySelector('[data-quick-attachment-input]');
const autoAttachmentFlag = document.querySelector('[data-auto-attachment-flag]');

if (quickAttachTrigger && quickAttachInput) {
  const updateForm = quickAttachInput.closest('form');

  if (updateForm) {
    const resetFlag = () => {
      if (autoAttachmentFlag) {
        autoAttachmentFlag.value = '0';
      }
    };

    const hasFilesSelected = () =>
      Boolean(quickAttachInput.files && quickAttachInput.files.length > 0);

    const submitForm = () => {
      if (typeof updateForm.requestSubmit === 'function') {
        updateForm.requestSubmit();
      } else {
        updateForm.submit();
      }
    };

    quickAttachTrigger.addEventListener('click', (event) => {
      event.preventDefault();
      resetFlag();
      quickAttachInput.value = '';
      quickAttachInput.click();
    });

    quickAttachInput.addEventListener('change', () => {
      if (hasFilesSelected()) {
        if (autoAttachmentFlag) {
          autoAttachmentFlag.value = '1';
        }
        submitForm();
      } else {
        resetFlag();
      }
    });

    quickAttachInput.addEventListener('input', () => {
      if (!hasFilesSelected()) {
        resetFlag();
      }
    });

    quickAttachInput.addEventListener('cancel', resetFlag);
  }
}
