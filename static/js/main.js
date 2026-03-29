/* ─── Naijamirage Main JS ──────────────────────────────────────────────────── */

// ─── Mobile Nav ───────────────────────────────────────────────────────────────
const hamburger = document.getElementById('hamburger');
const mobileMenu = document.getElementById('mobileMenu');
if (hamburger && mobileMenu) {
  hamburger.addEventListener('click', () => {
    mobileMenu.classList.toggle('open');
  });
  document.addEventListener('click', (e) => {
    if (!hamburger.contains(e.target) && !mobileMenu.contains(e.target)) {
      mobileMenu.classList.remove('open');
    }
  });
}

// ─── Active Nav Link ──────────────────────────────────────────────────────────
(function markActiveNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.navbar-links a, .mobile-menu a').forEach(link => {
    const href = link.getAttribute('href');
    if (href === path || (href !== '/' && path.startsWith(href))) {
      link.classList.add('active');
    }
  });
})();

// ─── Audio Players ────────────────────────────────────────────────────────────
let currentAudio = null;
let currentPlayBtn = null;

function formatTime(secs) {
  if (isNaN(secs)) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function initAudioPlayers() {
  document.querySelectorAll('[data-audio-card]').forEach(card => {
    const trackId  = card.dataset.trackId;
    const streamUrl = card.dataset.streamUrl;
    const playBtn  = card.querySelector('.play-btn');
    const progressWrap = card.querySelector('.progress-wrap');
    const progressBar  = card.querySelector('.progress-bar');
    const timeDisplay  = card.querySelector('.time-display');
    const volumeSlider = card.querySelector('.volume-slider');

    if (!playBtn || !streamUrl) return;

    let audio = null;

    function getOrCreateAudio() {
      if (!audio) {
        audio = new Audio(streamUrl);
        audio.addEventListener('timeupdate', () => {
          if (!audio.duration) return;
          const pct = (audio.currentTime / audio.duration) * 100;
          if (progressBar) progressBar.style.width = pct + '%';
          if (timeDisplay) timeDisplay.textContent =
            `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
        });
        audio.addEventListener('ended', () => {
          playBtn.innerHTML = '&#9654;';
          if (progressBar) progressBar.style.width = '0%';
          if (timeDisplay) timeDisplay.textContent = '0:00';
        });
        audio.addEventListener('error', () => {
          playBtn.innerHTML = '&#9654;';
        });
      }
      return audio;
    }

    playBtn.addEventListener('click', () => {
      const a = getOrCreateAudio();
      // Pause any other playing audio
      if (currentAudio && currentAudio !== a) {
        currentAudio.pause();
        if (currentPlayBtn) currentPlayBtn.innerHTML = '&#9654;';
      }
      if (a.paused) {
        a.play().catch(() => {});
        playBtn.innerHTML = '&#9646;&#9646;';
        currentAudio = a;
        currentPlayBtn = playBtn;
      } else {
        a.pause();
        playBtn.innerHTML = '&#9654;';
      }
    });

    if (progressWrap) {
      progressWrap.addEventListener('click', (e) => {
        const a = getOrCreateAudio();
        if (!a.duration) return;
        const rect = progressWrap.getBoundingClientRect();
        const pct = (e.clientX - rect.left) / rect.width;
        a.currentTime = pct * a.duration;
      });
    }

    if (volumeSlider) {
      volumeSlider.addEventListener('input', () => {
        const a = getOrCreateAudio();
        a.volume = volumeSlider.value;
      });
    }
  });
}

// ─── Video Modal ──────────────────────────────────────────────────────────────
function initVideoModals() {
  const modal = document.getElementById('videoModal');
  const modalVideo = document.getElementById('modalVideo');
  const modalClose = document.getElementById('modalClose');
  if (!modal || !modalVideo) return;

  document.querySelectorAll('[data-video-thumb]').forEach(thumb => {
    thumb.addEventListener('click', () => {
      const src = thumb.dataset.streamUrl;
      if (!src) return;
      modalVideo.src = src;
      modal.classList.add('open');
      modalVideo.play().catch(() => {});
    });
  });

  function closeModal() {
    modal.classList.remove('open');
    modalVideo.pause();
    modalVideo.src = '';
  }

  if (modalClose) modalClose.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('open')) closeModal();
  });
}

// ─── Upload Tab Switcher ──────────────────────────────────────────────────────
function initUploadTabs() {
  const tabs = document.querySelectorAll('.upload-tab');
  const panels = document.querySelectorAll('.upload-panel');
  if (!tabs.length) return;

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;
      tabs.forEach(t => t.classList.remove('active'));
      panels.forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      const panel = document.getElementById(`panel-${target}`);
      if (panel) panel.classList.add('active');
    });
  });
}

// ─── File Drop Zone ───────────────────────────────────────────────────────────
function initFileDrops() {
  document.querySelectorAll('.file-drop').forEach(drop => {
    const input = drop.querySelector('input[type="file"]');
    const nameDisplay = drop.querySelector('.file-name-display');
    if (!input) return;

    input.addEventListener('change', () => {
      if (input.files.length && nameDisplay) {
        nameDisplay.textContent = '📎 ' + input.files[0].name;
      }
    });

    drop.addEventListener('dragover', (e) => {
      e.preventDefault();
      drop.classList.add('dragover');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
    drop.addEventListener('drop', (e) => {
      e.preventDefault();
      drop.classList.remove('dragover');
      if (input && e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        if (nameDisplay) nameDisplay.textContent = '📎 ' + e.dataTransfer.files[0].name;
      }
    });
  });
}

// ─── Upload Progress ──────────────────────────────────────────────────────────
function initUploadForms() {
  document.querySelectorAll('[data-upload-form]').forEach(form => {
    const container = form.querySelector('.progress-container');
    const bar       = form.querySelector('.upload-progress-bar');
    const text      = form.querySelector('.upload-progress-text');
    const submitBtn = form.querySelector('[type="submit"]');

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', form.action);

      if (container) container.classList.add('visible');
      if (submitBtn) submitBtn.disabled = true;

      xhr.upload.addEventListener('progress', (evt) => {
        if (!evt.lengthComputable) return;
        const pct = Math.round((evt.loaded / evt.total) * 100);
        if (bar) bar.style.width = pct + '%';
        if (text) text.textContent = `Uploading… ${pct}%`;
      });

      xhr.addEventListener('load', () => {
        if (bar) bar.style.width = '100%';
        if (text) text.textContent = 'Upload complete! Redirecting…';
        // Follow the redirect the server sends
        window.location.href = xhr.responseURL || '/';
      });

      xhr.addEventListener('error', () => {
        if (text) text.textContent = 'Upload failed. Please try again.';
        if (submitBtn) submitBtn.disabled = false;
      });

      xhr.send(fd);
    });
  });
}

// ─── Flash Auto-dismiss ───────────────────────────────────────────────────────
function initFlashDismiss() {
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity 0.5s ease';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 5000);
  });
}

// ─── Ticker duplication ───────────────────────────────────────────────────────
function initTicker() {
  const ticker = document.querySelector('.ticker');
  if (!ticker) return;
  // Duplicate so the scroll is seamless
  ticker.innerHTML += ticker.innerHTML;
}

// ─── Lazy image loading ───────────────────────────────────────────────────────
function initLazyImages() {
  if (!('IntersectionObserver' in window)) return;
  const obs = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const img = entry.target;
        if (img.dataset.src) {
          img.src = img.dataset.src;
          img.removeAttribute('data-src');
        }
        obs.unobserve(img);
      }
    });
  }, { rootMargin: '200px' });
  document.querySelectorAll('img[data-src]').forEach(img => obs.observe(img));
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initAudioPlayers();
  initVideoModals();
  initUploadTabs();
  initFileDrops();
  initUploadForms();
  initFlashDismiss();
  initTicker();
  initLazyImages();
});
