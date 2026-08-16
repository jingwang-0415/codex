(() => {
    const body = document.body;
    const stage = document.querySelector('main');
    const slides = [...document.querySelectorAll('.slide')];
    const dots = document.querySelector('.deck-dots');
    const progress = document.querySelector('.deck-progress span');
    const currentLabel = document.querySelector('.deck-counter b');
    const totalLabel = document.querySelector('.deck-counter span');
    const prevButton = document.querySelector('[data-action="prev"]');
    const nextButton = document.querySelector('[data-action="next"]');
    const fullscreenButton = document.querySelector('[data-action="fullscreen"]');
    const imageAssets = window.DECK_CONFIG?.images || {};
    let current = 0;
    let pointerStartX = null;
    let pointerStartY = null;
    let suppressSlideClick = false;

    body.classList.add('interactive-mode');
    stage.classList.add('deck-stage');
    totalLabel.textContent = slides.length;

    document.querySelectorAll('[data-image]').forEach((image) => {
      const source = imageAssets[image.dataset.image];
      const photoShell = image.closest('[data-photo-shell]');
      if (!source) {
        image.hidden = true;
        return;
      }

      image.src = source;
      image.hidden = false;
      photoShell?.classList.add('has-image');
      image.addEventListener('error', () => {
        image.hidden = true;
        photoShell?.classList.remove('has-image');
      });
    });

    const slideTitle = (slide, index) => {
      const title = slide.querySelector('.title, h1');
      return title ? title.textContent.replace(/\s+/g, ' ').trim() : `第 ${index + 1} 页`;
    };

    const revealDefinitions = [
      { slideIndex: 1, groupSelector: '.rise-chart', itemSelector: '.rise-node, .rise-honor' },
      { slideIndex: 2, groupSelector: '.case-columns', itemSelector: '.case-card' },
      { slideIndex: 3, groupSelector: '.optimization-columns', itemSelector: '.optimization-case' },
      { slideIndex: 4, groupSelector: '.closure-lanes', itemSelector: '.closure-lane, .delivery-convergence' },
      { slideIndex: 5, groupSelector: '.summary-columns', itemSelector: '.summary-card' }
    ];
    const revealGroups = new Map();

    const setRevealFocus = (slideIndex, index) => {
      const reveal = revealGroups.get(slideIndex);
      if (!reveal) return;
      reveal.focusedIndex = index >= 0 && index < reveal.items.length ? index : -1;
      reveal.items.forEach((item, itemIndex) => {
        const active = itemIndex === reveal.focusedIndex;
        item.classList.toggle('is-revealed', active);
        item.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
    };

    revealDefinitions.forEach(({ slideIndex, groupSelector, itemSelector }) => {
      const group = slides[slideIndex]?.querySelector(groupSelector);
      const items = group ? [...group.querySelectorAll(itemSelector)] : [];
      if (!group || !items.length) return;

      group.classList.add('reveal-ready');
      revealGroups.set(slideIndex, { group, items, focusedIndex: -1 });
      items.forEach((item, index) => {
        const titleNode = item.querySelector('h3, .lane-title strong, .summary-card-head h3, strong');
        const title = titleNode?.textContent.replace(/\s+/g, ' ').trim() || `主题 ${index + 1}`;
        item.classList.add('reveal-item');
        item.tabIndex = 0;
        item.setAttribute('role', 'button');
        item.setAttribute('aria-label', `聚焦讲述：${title}`);
        item.setAttribute('aria-pressed', 'false');
        item.addEventListener('click', (event) => {
          event.stopPropagation();
          const reveal = revealGroups.get(slideIndex);
          setRevealFocus(slideIndex, reveal.focusedIndex === index ? -1 : index);
        });
        item.addEventListener('keydown', (event) => {
          if (event.key !== 'Enter') return;
          event.preventDefault();
          event.stopPropagation();
          const reveal = revealGroups.get(slideIndex);
          setRevealFocus(slideIndex, reveal.focusedIndex === index ? -1 : index);
        });
      });
    });

    slides.forEach((slide, index) => {
      slide.setAttribute('role', 'group');
      slide.setAttribute('aria-roledescription', '幻灯片');
      slide.setAttribute('aria-label', `${index + 1} / ${slides.length}：${slideTitle(slide, index)}`);

      const dot = document.createElement('button');
      dot.type = 'button';
      dot.className = 'deck-dot';
      dot.setAttribute('aria-label', `跳转到第 ${index + 1} 页`);
      dot.title = slideTitle(slide, index);
      dot.addEventListener('click', () => goTo(index));
      dots.appendChild(dot);

      slide.addEventListener('click', (event) => {
        if (suppressSlideClick || event.target.closest('a, button, input, textarea, select')) return;
        goTo(current + 1);
      });
    });

    const fitDeck = () => {
      const fullscreen = Boolean(document.fullscreenElement);
      const horizontalRoom = Math.max(280, window.innerWidth - (fullscreen ? 0 : 32));
      const verticalRoom = Math.max(180, window.innerHeight - (fullscreen ? 0 : 92));
      const scale = Math.min(
        horizontalRoom / 960,
        verticalRoom / 540,
        fullscreen ? Number.POSITIVE_INFINITY : 1.25
      );
      body.classList.toggle('is-fullscreen', fullscreen);
      body.style.setProperty('--deck-scale', scale.toFixed(4));
    };

    const goTo = (index) => {
      current = Math.max(0, Math.min(slides.length - 1, index));
      revealGroups.forEach((_, slideIndex) => {
        if (slideIndex !== current) setRevealFocus(slideIndex, -1);
      });
      slides.forEach((slide, slideIndex) => {
        slide.classList.toggle('is-before', slideIndex < current);
        slide.classList.toggle('is-active', slideIndex === current);
        slide.classList.toggle('is-after', slideIndex > current);
        slide.setAttribute('aria-hidden', slideIndex === current ? 'false' : 'true');
      });

      [...dots.children].forEach((dot, dotIndex) => {
        const active = dotIndex === current;
        dot.classList.toggle('is-active', active);
        dot.setAttribute('aria-current', active ? 'page' : 'false');
      });

      currentLabel.textContent = current + 1;
      progress.style.width = `${((current + 1) / slides.length) * 100}%`;
      prevButton.disabled = current === 0;
      nextButton.disabled = current === slides.length - 1;
      history.replaceState(null, '', `#slide-${current + 1}`);
    };

    const toggleFullscreen = async () => {
      try {
        if (!document.fullscreenElement) {
          await document.documentElement.requestFullscreen();
        } else {
          await document.exitFullscreen();
        }
      } catch (_) {
        // Some file:// browser contexts disable the Fullscreen API.
      }
    };

    prevButton.addEventListener('click', () => goTo(current - 1));
    nextButton.addEventListener('click', () => goTo(current + 1));
    fullscreenButton.addEventListener('click', toggleFullscreen);

    window.addEventListener('keydown', (event) => {
      const reveal = revealGroups.get(current);
      if (reveal && /^[1-9]$/.test(event.key) && Number(event.key) <= reveal.items.length) {
        event.preventDefault();
        setRevealFocus(current, Number(event.key) - 1);
      } else if (reveal && ['0', 'Escape'].includes(event.key) && reveal.focusedIndex >= 0) {
        event.preventDefault();
        setRevealFocus(current, -1);
      } else if (reveal && ['ArrowRight', 'PageDown', ' '].includes(event.key)) {
        event.preventDefault();
        if (reveal.focusedIndex < reveal.items.length - 1) {
          setRevealFocus(current, reveal.focusedIndex + 1);
        } else {
          goTo(current + 1);
        }
      } else if (reveal && ['ArrowLeft', 'PageUp'].includes(event.key)) {
        event.preventDefault();
        if (reveal.focusedIndex >= 0) {
          setRevealFocus(current, reveal.focusedIndex - 1);
        } else {
          goTo(current - 1);
        }
      } else if (['ArrowRight', 'PageDown', ' '].includes(event.key)) {
        event.preventDefault();
        goTo(current + 1);
      } else if (['ArrowLeft', 'PageUp'].includes(event.key)) {
        event.preventDefault();
        goTo(current - 1);
      } else if (event.key === 'Home') {
        goTo(0);
      } else if (event.key === 'End') {
        goTo(slides.length - 1);
      } else if (event.key.toLowerCase() === 'f') {
        toggleFullscreen();
      }
    });

    stage.addEventListener('pointerdown', (event) => {
      pointerStartX = event.clientX;
      pointerStartY = event.clientY;
    });

    stage.addEventListener('pointerup', (event) => {
      if (pointerStartX === null || pointerStartY === null) return;
      const deltaX = event.clientX - pointerStartX;
      const deltaY = event.clientY - pointerStartY;
      if (Math.abs(deltaX) > 54 && Math.abs(deltaX) > Math.abs(deltaY) * 1.2) {
        suppressSlideClick = true;
        goTo(current + (deltaX < 0 ? 1 : -1));
        window.setTimeout(() => { suppressSlideClick = false; }, 250);
      }
      pointerStartX = null;
      pointerStartY = null;
    });

    window.addEventListener('resize', fitDeck);
    document.addEventListener('fullscreenchange', fitDeck);
    window.addEventListener('hashchange', () => {
      const match = location.hash.match(/slide-(\d+)/);
      if (match) goTo(Number(match[1]) - 1);
    });

    const hashMatch = location.hash.match(/slide-(\d+)/);
    fitDeck();
    goTo(hashMatch ? Number(hashMatch[1]) - 1 : 0);
  })();
