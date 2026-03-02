/**
 * claw-forge website — main.js
 * - Copy-to-clipboard for all pre>code blocks
 * - Smooth scroll for anchor links
 * - Toast notifications
 * - Highlight.js init
 */

// ── Toast notification ────────────────────────────────────────────────────────

let _toastTimer = null;

function showToast(message) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add('show');

  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove('show'), 2000);
}

// ── Copy to clipboard ─────────────────────────────────────────────────────────

function addCopyButtons() {
  document.querySelectorAll('pre').forEach(pre => {
    // Skip if already has a button
    if (pre.querySelector('.copy-btn')) return;

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = 'Copy';

    btn.addEventListener('click', async () => {
      const code = pre.querySelector('code');
      const text = code ? code.innerText : pre.innerText;
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        showToast('✅ Copied to clipboard!');
        setTimeout(() => {
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }, 2000);
      } catch {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        btn.textContent = 'Copied!';
        showToast('✅ Copied!');
        setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
      }
    });

    pre.style.position = 'relative';
    pre.appendChild(btn);
  });
}

// ── Smooth scroll for anchor links ────────────────────────────────────────────

function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', e => {
      const target = document.querySelector(anchor.getAttribute('href'));
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

// ── Highlight.js init ─────────────────────────────────────────────────────────

function initHighlight() {
  if (typeof hljs !== 'undefined') {
    hljs.configure({ ignoreUnescapedHTML: true });
    hljs.highlightAll();
  }
}

// ── Active nav link ───────────────────────────────────────────────────────────

function initActiveNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-links a').forEach(link => {
    const href = link.getAttribute('href');
    if (href && path.endsWith(href)) {
      link.style.color = 'var(--text)';
      link.style.fontWeight = '600';
    }
  });
}

// ── Intersection observer for fade-in cards ───────────────────────────────────

function initFadeIn() {
  const observer = new IntersectionObserver(
    entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
        }
      });
    },
    { threshold: 0.1 }
  );

  document.querySelectorAll('.card, .step').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    observer.observe(el);
  });
}

// ── Table row highlight ───────────────────────────────────────────────────────

function initTableHighlight() {
  document.querySelectorAll('table.comparison tbody tr').forEach(row => {
    const cells = row.querySelectorAll('td');
    // If claw-forge column has ✅ and autoforge has ❌, highlight row
    if (cells.length >= 3) {
      const autoforge = cells[1].textContent.trim();
      const clawforge = cells[2].textContent.trim();
      if (autoforge.includes('❌') && clawforge.includes('✅')) {
        row.style.background = 'rgba(63, 185, 80, 0.04)';
      }
    }
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initHighlight();
  addCopyButtons();
  initSmoothScroll();
  initActiveNav();
  initFadeIn();
  initTableHighlight();
});
