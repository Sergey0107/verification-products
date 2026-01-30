const modal = document.querySelector('[data-modal]');
const openButton = document.querySelector('[data-open]');
const list = document.querySelector('[data-list]');
const uploadForm = document.querySelector('[data-upload-form]');

const renderItem = (item) => {
  const tzLink = item.tz_id
    ? `<a class="file-link" href="/files/${item.tz_id}/download">${item.tz}</a>`
    : item.tz || '';
  const passportLink = item.passport_id
    ? `<a class="file-link" href="/files/${item.passport_id}/download">${item.passport}</a>`
    : item.passport || '';

  return `
    <article class="list-item" data-analysis-id="${item.analysis_id}">
      <div class="meta">
        <p class="meta-label">Техническое задание:</p>
        <p class="meta-value">${tzLink}</p>
      </div>
      <div class="meta">
        <p class="meta-label">Паспорт изделия:</p>
        <p class="meta-value">${passportLink}</p>
      </div>
      <div class="meta">
        <p class="meta-label">Статус:</p>
        <p class="status status-${item.status_key}" data-status>${item.status}</p>
      </div>
      <button class="btn btn-outline" type="button">Открыть</button>
    </article>
  `;
};

const refreshList = async () => {
  if (!list) return;
  const response = await fetch('/api/analyses', { credentials: 'same-origin' });
  if (!response.ok) return;
  const data = await response.json();
  list.innerHTML = data.items.map(renderItem).join('');
};

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

  if (uploadForm) {
    uploadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const formData = new FormData(uploadForm);
      const response = await fetch('/files/upload', {
        method: 'POST',
        body: formData,
      });
      if (response.ok) {
        closeModal();
        uploadForm.reset();
        await refreshList();
      }
    });
  }
}

refreshList();
setInterval(refreshList, 4000);
