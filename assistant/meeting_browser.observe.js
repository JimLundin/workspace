(() => {
  const visible=e=>!!e && e.getClientRects().length>0 && getComputedStyle(e).visibility!=='hidden';
  const has=s=>[...document.querySelectorAll(s)].some(visible);
  const leaving=has('[data-tid="call-hangup"], [data-tid="hangup-button"], #hangup-button');
  const microphone=has('[data-tid="call-microphone"], #microphone-button');
  const joining=has('[data-tid="prejoin-join-button"], #prejoin-join-button');
  const lobby=has('[data-tid="lobby-screen"], [data-tid="calling-lobby-screen"]');
  const duration=[...document.querySelectorAll('[data-tid="call-duration"]')]
    .some(e=>visible(e) && /^(?:\d+:)?\d{1,2}:\d{2}$/.test(e.innerText.trim()));
  return {phase:leaving && microphone && duration && !joining && !lobby ? 'connected' : 'outside',
    title:document.title.slice(0,240)};
})()