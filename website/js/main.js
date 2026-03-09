/**
 * REFInet Pillar — Main JS
 * Unified modal system, scroll reveals, nav, tabs, clipboard, typewriter
 */
(function () {
  'use strict';

  // ── Doc file mapping ──
  var DOC_FILES = {
    'GETTING-STARTED': { file: 'docs/GETTING-STARTED.md', github: 'GETTING-STARTED.md', title: 'Getting Started' },
    'PLATFORM_OVERVIEW': { file: 'docs/PLATFORM_OVERVIEW.md', github: 'PLATFORM_OVERVIEW.md', title: 'Platform Overview' },
    'DEV_GUIDE': { file: 'docs/DEV_GUIDE.md', github: 'DEV_GUIDE.md', title: 'Developer Guide' },
    'WHITEPAPER': { file: 'docs/WHITEPAPER.md', github: 'WHITEPAPER.md', title: 'Whitepaper' },
    'SECURITY': { file: 'docs/SECURITY.md', github: 'SECURITY.md', title: 'Security Policy' },
    'CHANGELOG': { file: 'docs/CHANGELOG.md', github: 'CHANGELOG.md', title: 'Changelog' }
  };
  var GITHUB_BASE = 'https://github.com/circularityglobal/REFINET-PILLARS/blob/main/';
  var docCache = {};

  // ══════════════════════════════════════════
  // UNIFIED MODAL SYSTEM
  // ══════════════════════════════════════════

  var activeModal = null;

  function openModal(id) {
    // Close any currently open modal first
    if (activeModal) closeModal(activeModal);
    var modal = document.getElementById(id);
    if (!modal) return;
    activeModal = id;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
  }

  function closeModal(id) {
    var modal = document.getElementById(id || activeModal);
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (activeModal === (id || activeModal)) activeModal = null;
  }

  function closeActiveModal() {
    if (activeModal) closeModal(activeModal);
  }

  // Global: close on Escape
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeActiveModal();
  });

  // Global: close on backdrop click
  document.addEventListener('click', function (e) {
    if (e.target.classList.contains('arch-modal-backdrop')) closeActiveModal();
  });

  // Global: close buttons
  document.addEventListener('click', function (e) {
    var closeBtn = e.target.closest('[data-modal-close]');
    if (closeBtn) {
      closeActiveModal();
      // Check if this button should also open another modal
      var openNext = closeBtn.getAttribute('data-open-modal');
      if (openNext) {
        setTimeout(function () { openModal(openNext); }, 100);
      }
    }
  });

  // Global: data-modal link handler
  document.addEventListener('click', function (e) {
    var trigger = e.target.closest('[data-modal]');
    if (!trigger) return;
    e.preventDefault();

    var modalId = trigger.getAttribute('data-modal');
    var docSlug = trigger.getAttribute('data-doc');

    // Special handling: dl-modal footer link
    if (modalId === 'dl-modal') {
      openModal('dl-modal');
      return;
    }

    // If opening docs modal with a specific doc
    if (modalId === 'docs-modal' && docSlug) {
      openModal('docs-modal');
      switchDocsTo(docSlug);
      return;
    }

    // If opening docs modal without a specific doc, load first doc
    if (modalId === 'docs-modal') {
      openModal('docs-modal');
      if (!currentDocSlug) switchDocsTo('GETTING-STARTED');
      return;
    }

    openModal(modalId);
  });

  // ══════════════════════════════════════════
  // ARCHITECTURE MODAL (legacy wiring)
  // ══════════════════════════════════════════

  var archBtn = document.getElementById('arch-modal-btn');
  var archClose = document.getElementById('arch-modal-close');

  if (archBtn) {
    archBtn.addEventListener('click', function () { openModal('arch-modal'); });
  }
  if (archClose) {
    archClose.addEventListener('click', closeActiveModal);
  }

  // ══════════════════════════════════════════
  // DOWNLOAD MODAL
  // ══════════════════════════════════════════

  var dlBtn = document.getElementById('dl-modal-btn');
  var dlClose = document.getElementById('dl-modal-close');
  var dlModal = document.getElementById('dl-modal');

  if (dlBtn) {
    dlBtn.addEventListener('click', function () { openModal('dl-modal'); });
  }
  var navDlLink = document.getElementById('nav-download-link');
  if (navDlLink) {
    navDlLink.addEventListener('click', function (e) {
      e.preventDefault();
      openModal('dl-modal');
    });
  }
  if (dlClose) {
    dlClose.addEventListener('click', closeActiveModal);
  }

  // Download modal tab switching
  var dlTabBtns = document.querySelectorAll('.dl-tab-btn');
  var dlTabPanels = document.querySelectorAll('.dl-tab-panel');
  var dlTabSelect = document.querySelector('.dl-tab-select');

  function switchDlTab(id) {
    dlTabBtns.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === id);
    });
    dlTabPanels.forEach(function (p) {
      p.classList.toggle('active', p.id === id);
    });
    if (dlTabSelect) dlTabSelect.value = id;
  }
  dlTabBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      switchDlTab(btn.getAttribute('data-tab'));
    });
  });
  if (dlTabSelect) {
    dlTabSelect.addEventListener('change', function () {
      switchDlTab(dlTabSelect.value);
    });
  }

  // Auto-detect OS and pre-select the matching download tab
  (function () {
    var ua = navigator.userAgent || '';
    var tab = 'dl-tab-windows'; // default
    if (/Android/i.test(ua)) tab = 'dl-tab-mobile';
    else if (/Macintosh|Mac OS X/i.test(ua)) tab = 'dl-tab-macos';
    else if (/Linux/i.test(ua)) tab = 'dl-tab-linux';
    else if (/Windows/i.test(ua)) tab = 'dl-tab-windows';
    switchDlTab(tab);
  })();

  // Copy buttons inside download modal
  if (dlModal) {
    dlModal.querySelectorAll('.copy-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var block = btn.closest('.code-block');
        var code = block.querySelector('pre').textContent;
        navigator.clipboard.writeText(code).then(function () {
          btn.textContent = 'Copied!';
          btn.classList.add('copied');
          setTimeout(function () {
            btn.textContent = 'Copy';
            btn.classList.remove('copied');
          }, 2000);
        });
      });
    });
  }

  // ══════════════════════════════════════════
  // UNIFIED DOCS MODAL
  // ══════════════════════════════════════════

  var currentDocSlug = null;
  var docsModalTitle = document.getElementById('docs-modal-title');
  var docsNavItems = document.querySelectorAll('.docs-nav-item');

  function switchDocsTo(slug) {
    if (!DOC_FILES[slug]) return;
    currentDocSlug = slug;

    // Update nav sidebar active state
    docsNavItems.forEach(function (btn) {
      btn.classList.toggle('active', btn.getAttribute('data-doc-slug') === slug);
    });

    // Update modal title
    if (docsModalTitle) {
      docsModalTitle.textContent = DOC_FILES[slug].title;
    }

    // Load the doc content
    loadDocInModal(slug);
  }

  // Doc nav sidebar click handlers
  docsNavItems.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var slug = btn.getAttribute('data-doc-slug');
      switchDocsTo(slug);
    });
  });

  function loadDocInModal(slug) {
    var contentEl = document.getElementById('docs-modal-content');
    var tocEl = document.getElementById('docs-modal-toc');
    var info = DOC_FILES[slug];

    if (docCache[slug]) {
      renderDocModal(docCache[slug], contentEl, tocEl, slug.toLowerCase());
      contentEl.scrollTop = 0;
      return;
    }

    contentEl.innerHTML = '<div class="doc-loading">Loading document...</div>';
    tocEl.innerHTML = '';
    fetch(info.file)
      .then(function (res) {
        if (!res.ok) throw new Error('Failed to load');
        return res.text();
      })
      .then(function (md) {
        docCache[slug] = md;
        renderDocModal(md, contentEl, tocEl, slug.toLowerCase());
        contentEl.scrollTop = 0;
      })
      .catch(function () {
        contentEl.innerHTML = '<div class="doc-loading">Failed to load document. <a href="' +
          GITHUB_BASE + info.github + '" target="_blank" rel="noopener">View on GitHub</a></div>';
      });
  }

  // ── Shared Doc Modal Renderer ──
  function slugify(text) {
    return text.toLowerCase()
      .replace(/<[^>]*>/g, '')
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
  }

  function renderDocModal(md, contentEl, tocEl, prefix) {
    if (window.marked) {
      var renderer = new marked.Renderer();
      var headingCount = {};
      renderer.heading = function (textOrData, level) {
        var text, depth;
        if (typeof textOrData === 'object') {
          text = textOrData.text;
          depth = textOrData.depth;
        } else {
          text = textOrData;
          depth = level;
        }
        var raw = text.replace(/<[^>]*>/g, '');
        var slug = prefix + '-' + slugify(raw);
        if (headingCount[slug] !== undefined) {
          headingCount[slug]++;
          slug = slug + '-' + headingCount[slug];
        } else {
          headingCount[slug] = 0;
        }
        return '<h' + depth + ' id="' + slug + '">' +
          '<a class="heading-anchor" href="#' + slug + '" aria-hidden="true">#</a>' +
          text + '</h' + depth + '>\n';
      };
      marked.setOptions({ gfm: true, breaks: false });
      contentEl.innerHTML = marked.parse(md, { renderer: renderer });
    } else {
      contentEl.innerHTML = '<pre>' + md.replace(/</g, '&lt;') + '</pre>';
    }

    // Build TOC from rendered headings
    var headings = contentEl.querySelectorAll('h1, h2, h3');
    var tocHtml = '';
    headings.forEach(function (h) {
      var level = h.tagName.toLowerCase();
      var text = h.textContent.replace(/^#\s*/, '');
      tocHtml += '<a href="#' + h.id + '" class="toc-' + level + '" title="' +
        text.replace(/"/g, '&quot;') + '">' + text + '</a>';
    });
    tocEl.innerHTML = tocHtml;

    // TOC link clicks scroll within the modal content area
    tocEl.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var targetId = a.getAttribute('href').substring(1);
        var target = document.getElementById(targetId);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          tocEl.querySelectorAll('a').forEach(function (t) { t.classList.remove('active'); });
          a.classList.add('active');
        }
      });
    });

    // Scroll-spy within the modal content area
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var id = entry.target.id;
          tocEl.querySelectorAll('a').forEach(function (a) {
            a.classList.toggle('active', a.getAttribute('href') === '#' + id);
          });
        }
      });
    }, {
      root: contentEl.parentElement,
      rootMargin: '-20px 0px -60% 0px',
      threshold: 0
    });
    headings.forEach(function (h) { observer.observe(h); });

    // Add copy buttons to code blocks
    contentEl.querySelectorAll('pre').forEach(function (pre) {
      if (pre.querySelector('.copy-btn')) return;
      var btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = 'Copy';
      btn.setAttribute('aria-label', 'Copy code');
      btn.addEventListener('click', function () {
        var code = pre.querySelector('code') || pre;
        navigator.clipboard.writeText(code.textContent).then(function () {
          btn.textContent = 'Copied!';
          btn.classList.add('copied');
          setTimeout(function () {
            btn.textContent = 'Copy';
            btn.classList.remove('copied');
          }, 2000);
        });
      });
      pre.style.position = 'relative';
      pre.appendChild(btn);
    });
  }

  // ══════════════════════════════════════════
  // TYPEWRITER EFFECT
  // ══════════════════════════════════════════

  var heroH1 = document.getElementById('hero-title');
  var typewriterDone = false;
  function runTypewriter() {
    if (typewriterDone || !heroH1) return;
    typewriterDone = true;
    var text = heroH1.getAttribute('data-text');
    heroH1.innerHTML = '<span class="cursor"></span>';
    var i = 0;
    function type() {
      if (i < text.length) {
        heroH1.innerHTML = text.slice(0, i + 1) + '<span class="cursor"></span>';
        i++;
        setTimeout(type, 55);
      }
    }
    setTimeout(type, 600);
  }

  // ══════════════════════════════════════════
  // SCROLL REVEAL
  // ══════════════════════════════════════════

  var reveals = document.querySelectorAll('.reveal');
  var revealObserver = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });
  reveals.forEach(function (el) { revealObserver.observe(el); });

  // ══════════════════════════════════════════
  // NAV SCROLL STATE
  // ══════════════════════════════════════════

  var nav = document.querySelector('.nav');
  window.addEventListener('scroll', function () {
    if (window.scrollY > 40) {
      nav.classList.add('scrolled');
    } else {
      nav.classList.remove('scrolled');
    }
  }, { passive: true });

  // ══════════════════════════════════════════
  // HAMBURGER MENU
  // ══════════════════════════════════════════

  var hamburger = document.querySelector('.hamburger');
  var navLinks = document.querySelector('.nav-links');
  if (hamburger) {
    hamburger.addEventListener('click', function () {
      hamburger.classList.toggle('active');
      navLinks.classList.toggle('open');
    });
    navLinks.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        hamburger.classList.remove('active');
        navLinks.classList.remove('open');
      });
    });
  }

  // ══════════════════════════════════════════
  // DOWNLOAD TABS (landing page)
  // ══════════════════════════════════════════

  var tabBtns = document.querySelectorAll('.tab-btn:not(.dl-tab-btn)');
  var tabPanels = document.querySelectorAll('.tab-panel:not(.dl-tab-panel)');
  var tabSelect = document.querySelector('.tab-select-mobile:not(.dl-tab-select)');

  function switchTab(id) {
    tabBtns.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === id);
    });
    tabPanels.forEach(function (p) {
      p.classList.toggle('active', p.id === id);
    });
    if (tabSelect) tabSelect.value = id;
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      switchTab(btn.getAttribute('data-tab'));
    });
  });
  if (tabSelect) {
    tabSelect.addEventListener('change', function () {
      switchTab(tabSelect.value);
    });
  }

  // ══════════════════════════════════════════
  // COPY TO CLIPBOARD (landing page)
  // ══════════════════════════════════════════

  document.querySelectorAll('#landing-page .copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var block = btn.closest('.code-block');
      var code = block.querySelector('pre').textContent;
      navigator.clipboard.writeText(code).then(function () {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(function () {
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }, 2000);
      });
    });
  });

  // ══════════════════════════════════════════
  // SMOOTH SCROLL FOR ANCHOR LINKS
  // ══════════════════════════════════════════

  document.addEventListener('click', function (e) {
    var link = e.target.closest('a[href^="#"]');
    if (!link) return;
    // Skip if it has a data-modal attribute (handled by modal system)
    if (link.hasAttribute('data-modal')) return;
    var href = link.getAttribute('href');
    if (href === '#') return;
    var target = document.querySelector(href);
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth' });
      history.replaceState(null, '', href);
    }
  });

  // ══════════════════════════════════════════
  // INIT
  // ══════════════════════════════════════════

  runTypewriter();

})();
