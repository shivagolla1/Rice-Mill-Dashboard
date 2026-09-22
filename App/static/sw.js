/* ==========================================================
   Rice Mill Dashboard — Service Worker
   Handles Web Push notifications for PWA (iPhone / Android)
   ========================================================== */

const SW_VERSION = '1.0.0';

/* ── PUSH EVENT: show native notification ── */
self.addEventListener('push', function (event) {
  let data = { title: '📂 Rice Mill', body: 'New database file uploaded!', url: '/' };

  if (event.data) {
    try {
      data = Object.assign(data, event.data.json());
    } catch (e) {
      data.body = event.data.text() || data.body;
    }
  }

  const options = {
    body: data.body,
    icon: '/logo',
    badge: '/logo',
    tag: 'upload-notification',          // replaces previous if still visible
    renotify: true,
    requireInteraction: false,
    data: { url: data.url || '/' }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

/* ── NOTIFICATION CLICK: open / focus the dashboard ── */
self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (windowClients) {
      for (let client of windowClients) {
        if (client.url.includes(targetUrl) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});

/* ── INSTALL / ACTIVATE: no caching — keep it minimal ── */
self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(clients.claim());
});
