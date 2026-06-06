(function() {
    'use strict';

    var loader = document.getElementById('terraViewGlobalLoader');
    var startedAt = Date.now();
    var minimumVisibleTime = 2600;
    var fallbackVisibleTime = 3400;
    var hideTimer = null;
    var fallbackTimer = null;
    function isCompanySelectionPath(pathname) {
        return pathname === '/seleccionar_empresa/' || pathname.indexOf('/cambiar_empresa/') === 0;
    }

    function shouldShowOnLoad() {
        if (isCompanySelectionPath(window.location.pathname)) {
            return false;
        }

        return true;
    }

    if (!loader) {
        return;
    }

    if (isCompanySelectionPath(window.location.pathname)) {
        loader.classList.add('is-hidden');
        loader.setAttribute('aria-hidden', 'true');
        return;
    }

    function hideLoader() {
        var elapsed = Date.now() - startedAt;
        var wait = Math.max(0, minimumVisibleTime - elapsed);

        window.clearTimeout(hideTimer);
        hideTimer = window.setTimeout(function() {
            loader.classList.add('is-hiding');
            loader.style.pointerEvents = 'none';
            window.setTimeout(function() {
                loader.classList.add('is-hidden');
                loader.setAttribute('aria-hidden', 'true');
            }, 460);
        }, wait);
    }

    function showLoader() {
        window.clearTimeout(hideTimer);
        loader.classList.remove('is-hidden', 'is-hiding');
        loader.style.pointerEvents = 'auto';
        loader.removeAttribute('aria-hidden');
        startedAt = Date.now();
    }

    if (shouldShowOnLoad()) {
        showLoader();
        document.addEventListener('DOMContentLoaded', hideLoader);
        window.addEventListener('load', hideLoader);
        fallbackTimer = window.setTimeout(hideLoader, fallbackVisibleTime);
        if (document.readyState === 'interactive' || document.readyState === 'complete') {
            hideLoader();
        }
    } else {
        loader.classList.add('is-hidden');
        loader.setAttribute('aria-hidden', 'true');
    }

    window.addEventListener('pageshow', function(event) {
        if (event.persisted) {
            loader.classList.add('is-hidden');
            loader.setAttribute('aria-hidden', 'true');
        }
    });

    document.addEventListener('submit', function(event) {
        var form = event.target;

        if (event.defaultPrevented || !form || (form.target && form.target !== '_self')) {
            return;
        }

        if (form.id === 'form-logout' || form.querySelector('[name="login"]')) {
            showLoader();
        }
    });
})();
