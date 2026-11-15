// Install in a private Google Apps Script project. Never store the secret in Git.
function request_(path, payload) {
  const props = PropertiesService.getScriptProperties();
  const root = (props.getProperty('APP_URL') || '').replace(/\/$/, '');
  const token = props.getProperty('SCHEDULER_SECRET');
  if (!/^https:\/\/[^/]+$/.test(root) || !token) throw new Error('Set HTTPS APP_URL and SCHEDULER_SECRET');
  const response = UrlFetchApp.fetch(root + path, {
    method: 'post', headers: {'X-Scheduler-Token': token},
    contentType: 'application/json', payload: JSON.stringify(payload || {}),
    muteHttpExceptions: true, followRedirects: false
  });
  if (response.getResponseCode() !== 200) throw new Error('Backend HTTP ' + response.getResponseCode());
  return JSON.parse(response.getContentText());
}
function runCareReminders() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const quota = MailApp.getRemainingDailyQuota();
    if (quota < 1) { request_('/internal/carepulse/refresh'); return; }
    const batch = request_('/internal/email/dispatch?limit=' + Math.min(10, quota)).messages;
    for (const message of batch) {
      let status = 'sent';
      try { MailApp.sendEmail(message.to, message.subject, message.body + '\n\nOpen: ' + PropertiesService.getScriptProperties().getProperty('APP_URL')); }
      catch (_) { status = 'failed'; }
      try { request_('/internal/email/' + message.id + '/result', {status: status}); }
      catch (_) { console.error('Could not acknowledge attempt ' + message.id); }
    }
    console.log('Processed ' + batch.length + ' reminder attempts');
  } finally { lock.releaseLock(); }
}
function installTrigger() {
  for (const t of ScriptApp.getProjectTriggers()) {
    if (t.getHandlerFunction() === 'runCareReminders') ScriptApp.deleteTrigger(t);
  }
  ScriptApp.newTrigger('runCareReminders').timeBased().everyMinutes(5).create();
}
