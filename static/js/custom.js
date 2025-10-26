
/* ============================================
   CUSTOM JAVASCRIPT FOR BUREAU BOOTHS APPLICATION

   This file provides utility functions for:
   - Loading state management
   - Auto-refresh functionality
   - Keyboard shortcuts
   - Error handling
   - Page visibility detection

   CONFIGURATION:
   - Auto-refresh interval: Change 60000 (60 seconds) to desired milliseconds
   - Keyboard shortcuts: Add/modify in the keydown event listener
   ============================================ */

/* ============================================
   LOADING STATE MANAGEMENT
   ============================================ */
/**
 * Display loading overlay with custom message
 * @param {string} message - Message to display (default: 'Loading...')
 *
 * Usage: showLoading('Fetching data...')
 */
function showLoading(message = 'Loading...') {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        const messageEl = overlay.querySelector('.text-white');
        if (messageEl) {
            messageEl.textContent = message;
        }
        overlay.classList.remove('hidden');
    }
}

/**
 * Hide the loading overlay
 *
 * Usage: hideLoading()
 */
function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

/* ============================================
   AUTO-REFRESH FUNCTIONALITY
   ============================================ */
// Global variable to track auto-refresh interval
let autoRefreshInterval;

/**
 * Start automatic page refresh at specified interval
 * @param {number} intervalMs - Interval in milliseconds (default: 60000 = 60 seconds)
 *
 * CUSTOMIZE: Change 60000 to your desired refresh interval
 * Examples:
 * - 30000 = 30 seconds
 * - 120000 = 2 minutes
 * - 300000 = 5 minutes
 */
function startAutoRefresh(intervalMs = 60000) {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }

    autoRefreshInterval = setInterval(() => {
        // Only refresh if page is visible (not in background tab)
        if (document.visibilityState === 'visible') {
            showLoading('Refreshing data...');
            location.reload();
        }
    }, intervalMs);
}

/**
 * Stop automatic page refresh
 *
 * Usage: stopAutoRefresh()
 */
function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

/* ============================================
   KEYBOARD SHORTCUTS
   ============================================ */
// Add keyboard shortcuts for better UX
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + R: Manual refresh (in addition to browser default)
    if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
        e.preventDefault();
        showLoading('Refreshing...');
        location.reload();
    }

    // Escape: Close mobile menu
    if (e.key === 'Escape') {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('mobileMenuOverlay');
        if (sidebar && overlay) {
            sidebar.classList.add('-translate-x-full');
            overlay.classList.add('hidden');
        }
    }
});

/* ============================================
   ERROR HANDLING
   ============================================ */
// Global error handler for debugging
window.addEventListener('error', function(e) {
    console.error('Application error:', e.error);
    // TODO: Add user-friendly error notifications here
    // Example: showNotification('An error occurred. Please refresh the page.');
});

/* ============================================
   PAGE VISIBILITY DETECTION
   ============================================ */
// Detect when page becomes visible/hidden (tab switching)
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible') {
        // Page became visible - could refresh data here
        console.log('Page became visible - data is current');
    } else {
        // Page became hidden - could pause auto-refresh
        console.log('Page became hidden - pausing auto-refresh');
    }
});

/* ============================================
   INITIALIZATION
   ============================================ */
// Initialize functionality when DOM is fully loaded
document.addEventListener('DOMContentLoaded', function() {
    // Start auto-refresh on dashboard and data pages
    // CUSTOMIZE: Adjust interval (60000 = 60 seconds) as needed
    if (window.location.pathname.includes('/dashboard') ||
        window.location.pathname.includes('/booth') ||
        window.location.pathname.includes('/location')) {
        startAutoRefresh(60000); // Refresh every 60 seconds
    }

    // Add loading states to all forms
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            showLoading('Processing...');
        });
    });

    // Add hover effects to all white cards
    const cards = document.querySelectorAll('.bg-white');
    cards.forEach(card => {
        card.classList.add('card-hover');
    });
});

/* ============================================
   PUBLIC API
   ============================================ */
// Export functions for use in other scripts
// Access via: window.BureauBooths.showLoading(), etc.
window.BureauBooths = {
    showLoading,      // Show loading overlay
    hideLoading,      // Hide loading overlay
    startAutoRefresh, // Start auto-refresh
    stopAutoRefresh   // Stop auto-refresh
};
