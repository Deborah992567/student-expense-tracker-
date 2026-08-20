// Vercel Speed Insights initialization
// This script initializes Speed Insights for the vanilla JS application

(function() {
  // Initialize the Speed Insights queue
  if (window.si) return;
  
  window.si = function(...params) {
    (window.siq = window.siq || []).push(params);
  };

  // Determine the script source based on environment
  const isDevelopment = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  const scriptSrc = isDevelopment 
    ? 'https://va.vercel-scripts.com/v1/speed-insights/script.debug.js'
    : '/_vercel/speed-insights/script.js';

  // Check if script is already loaded
  if (document.head.querySelector(`script[src*="${scriptSrc}"]`)) return;

  // Create and inject the Speed Insights script
  const script = document.createElement('script');
  script.src = scriptSrc;
  script.defer = true;
  script.dataset.sdkn = '@vercel/speed-insights';
  script.dataset.sdkv = '1.3.1';
  
  // Optional: Add custom configuration
  // script.dataset.sampleRate = '1'; // Track 100% of page views
  
  document.head.appendChild(script);
})();
