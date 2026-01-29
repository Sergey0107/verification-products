const modal = document.querySelector('[data-modal]');
const openButton = document.querySelector('[data-open]');

if (modal && openButton) {
  const closeTargets = modal.querySelectorAll('[data-close]');

  const openModal = () => {
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
  };

  const closeModal = () => {
    modal.hidden = true;
    document.body.style.overflow = '';
  };

  openButton.addEventListener('click', openModal);
  closeTargets.forEach((target) => target.addEventListener('click', closeModal));
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) {
      closeModal();
    }
  });
}
