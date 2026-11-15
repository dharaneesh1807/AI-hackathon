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
// Escape all inserted text before constructing email HTML.
function escapeHtml_(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function reminderEmail_(message, root) {
  const heading = message.subject.includes('follow-up') ? 'A care check-in is needed' :
    message.subject.includes('appointment') ? 'Your upcoming appointment' : 'Your medication reminder';
  const safeRoot = escapeHtml_(root);
  const content = escapeHtml_(message.body).replace(/\n/g, '<br>');
  return '<!doctype html><html lang="en"><body style="margin:0;padding:24px 8px;background:#eff5f2;font-family:Arial,sans-serif;color:#183d37;">' +
    '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">' +
    '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#fff;border:1px solid #d8e6df;border-radius:16px;overflow:hidden;">' +
    '<tr><td style="background:#124c45;color:#fff;padding:26px 30px;"><div style="font-size:20px;font-weight:bold;">Catalyst ElderCare</div><div style="font-size:13px;color:#d0e9dd;margin-top:6px;">CARE THAT FOLLOWS THROUGH</div></td></tr>' +
    '<tr><td style="padding:32px 30px;"><div style="font-size:12px;font-weight:bold;letter-spacing:1px;color:#176d60;">CARE WORKSPACE REMINDER</div>' +
    '<h1 style="font-size:26px;line-height:1.3;margin:12px 0 18px;color:#163b36;">' + escapeHtml_(heading) + '</h1>' +
    '<p style="font-size:16px;line-height:1.65;margin:0 0 24px;">' + content + '</p>' +
    '<a href="' + safeRoot + '" style="display:inline-block;background:#14665b;color:white;padding:14px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Open your care workspace</a>' +
    '<p style="font-size:13px;color:#526b63;line-height:1.5;margin:24px 0 0;">You can manage notification preferences in Care Circle → Email reminder settings.</p></td></tr>' +
    '<tr><td style="background:#e8f1eb;padding:18px 30px;font-size:12px;line-height:1.5;color:#435d53;">Care is a circle, not a checklist.<br>Private demo notification · No medical details are included.</td></tr>' +
    '</table></td></tr></table></body></html>';
}
// Voice is opt-in and independent of MailApp. Missing provider settings leave it disabled.
function runVoiceEscalations_() {
  const props = PropertiesService.getScriptProperties();
  const sid = props.getProperty('TWILIO_ACCOUNT_SID');
  const secret = props.getProperty('TWILIO_AUTH_TOKEN');
  const from = props.getProperty('TWILIO_FROM_NUMBER');
  if (!sid || !secret || !from) return;
  if (!/^AC[0-9a-f]{32}$/i.test(sid) || !/^\+[1-9]\d{7,14}$/.test(from)) throw new Error('Invalid voice provider configuration');
  const calls = request_('/internal/voice/dispatch?limit=3').calls;
  for (const call of calls) {
    let status = 'failed';
    try {
      const payload = {To:call.to, From:from, Twiml:'<Response><Say>Hello. This is Catalyst ElderCare. A care activity needs a follow-up. Please sign in to your care workspace or contact your care circle. This is a reminder, not an emergency alert.</Say></Response>'};
      // The optional official template supports restricted Twilio trial accounts.
      if (props.getProperty('TWILIO_TRIAL_TEMPLATE') === 'true') {
        delete payload.Twiml;
        payload.Url = 'https://webhooks.twilio.com/v1/Voice/Template/voice_text_to_speech';
      }
      const response = UrlFetchApp.fetch('https://api.twilio.com/2010-04-01/Accounts/'+sid+'/Calls.json', {
        method:'post', headers:{Authorization:'Basic '+Utilities.base64Encode(sid+':'+secret)},
        payload:payload, muteHttpExceptions:true, followRedirects:false
      });
      if (response.getResponseCode() === 201) status = 'accepted';
    } catch (_) { /* Ambiguous transport failures are not retried. */ }
    try { request_('/internal/voice/'+call.id+'/result',{status:status}); }
    catch (_) { console.error('Could not acknowledge voice attempt '+call.id); }
  }
  console.log('Processed '+calls.length+' voice requests');
}
function runCareReminders() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    try { runVoiceEscalations_(); } catch (_) { console.error('Voice escalation request failed; email processing continues'); }
    const quota = MailApp.getRemainingDailyQuota();
    if (quota < 1) { request_('/internal/carepulse/refresh'); return; }
    const batch = request_('/internal/email/dispatch?limit=' + Math.min(10, quota)).messages;
    for (const message of batch) {
      let status = 'sent';
      try {
        const root = PropertiesService.getScriptProperties().getProperty('APP_URL').replace(/\/$/, '');
        MailApp.sendEmail({to: message.to, subject: message.subject,
          body: message.body + '\n\nOpen: ' + root + '\nManage reminders in Care Circle > Email reminder settings.',
          htmlBody: reminderEmail_(message, root), name: 'Catalyst ElderCare'});
      }
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
