const state = {
  runId: null,
  storylineFlow: null,
  storylineFlowApproved: false,
  storyline: null,
  translated: null,
  dataset: null,
  selectedScene: 1,
  approved: false,
  translationProvider: 'sarvam',
  provider: 'azure',
  config: null,
  health: null,
};

const $ = (id) => document.getElementById(id);
const q = (s) => document.querySelector(s);
const qa = (s) => [...document.querySelectorAll(s)];

function escapeHtml(v = '') {
  return String(v).replace(/[&<>'"]/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  }[c]));
}

async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  let body = null;
  const text = await res.text();
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`);
  return body;
}

function toast(msg, error = false) {
  const el = $('toast');
  el.textContent = msg;
  el.className = `toast${error ? ' error' : ''}`;
  setTimeout(() => el.classList.add('hidden'), 3500);
}

function loading(title, copy = '') {
  const el = $('loading');
  $('loading-title').textContent = title;
  $('loading-copy').textContent = copy;
  el.classList.remove('hidden');
}

function done() {
  $('loading').classList.add('hidden');
}

function setStage(stage) {
  const order = ['setup', 'storyline', 'script', 'translate', 'voice', 'dataset'];
  const idx = order.indexOf(stage);
  qa('.pipe').forEach((el) => {
    const stepName = el.dataset.step;
    const stepIdx = order.indexOf(stepName);
    el.classList.toggle('complete', stepIdx < idx);
    el.classList.toggle('current', stepIdx === idx);
  });
}

async function init() {
  try {
    const [health, config] = await Promise.all([api('/api/health'), api('/api/config')]);
    state.health = health;
    state.config = config;
    const modeBadge = $('mode-badge');
    if (modeBadge) modeBadge.textContent = health.demoMode ? 'DEMO MODE' : 'LIVE MODE';
    $('language').innerHTML = config.languages
      .map((l) => `<option value="${l.id}">${escapeHtml(l.label)}</option>`)
      .join('');
    updateVoices();
  } catch (e) {
    toast('Backend unavailable: ' + e.message, true);
  }
}

function reset() {
  state.runId = null;
  state.storylineFlow = null;
  state.storylineFlowApproved = false;
  state.storyline = null;
  state.translated = null;
  state.dataset = null;
  state.selectedScene = 1;
  state.approved = false;

  $('custom-character').value = '';
  $('custom-setting').value = '';
  $('custom-story-idea').value = '';

  const runLabel = $('run-label');
  runLabel.textContent = 'No active run';
  runLabel.style.display = 'none';

  ['storyline-panel', 'review', 'translation-panel', 'voiceover', 'dataset'].forEach((id) =>
    $(id).classList.add('hidden')
  );

  $('approve-storyline').classList.remove('hidden');
  $('unlock-storyline').classList.add('hidden');
  $('generate-script-from-flow').disabled = true;

  $('approve').classList.remove('hidden');
  $('approve').disabled = false;
  $('unlock').classList.add('hidden');
  $('translate').disabled = true;
  $('make-voice').disabled = true;

  setStage('setup');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$('new-run').onclick = reset;

$('load-sample').onclick = () => {
  $('instruction').value =
    'Show six numbers for exactly 2 seconds. Hide one number and ask the child to identify it. Include one practice round and three formal trials, then give a short closing. Do not tell the child whether an answer was correct.';
  $('custom-character').value = 'Mira the moon rabbit';
  $('custom-setting').value = 'lantern lit forest';
  $('custom-story-idea').value = 'help find the missing flowers';
};

// --- STAGE 1: GENERATE GAMIFIED STORYLINE FLOW ---
$('generate-flow').onclick = async () => {
  const instruction = $('instruction').value.trim();
  if (instruction.length < 10) {
    toast('Please enter a more complete experiment description (at least 10 characters).', true);
    return;
  }
  try {
    loading('Generating Gamified Storyline Flow', 'Grok is structuring narrative adventure, rules & flow timings');
    const payload = {
      instruction,
      ageBand: $('age').value,
      duration: Number($('duration').value),
      targetLanguage: $('language').value,
      leadCharacter: $('custom-character').value.trim() || undefined,
      setting: $('custom-setting').value.trim() || undefined,
      storyIdea: $('custom-story-idea').value.trim() || undefined,
    };
    const r = await api('/api/generate-storyline', { method: 'POST', body: JSON.stringify(payload) });
    state.runId = r.runId;
    state.storylineFlow = r.storylineFlow;
    state.storylineFlowApproved = false;

    const runLabel = $('run-label');
    runLabel.textContent = r.runId;
    runLabel.style.display = 'inline-block';

    renderStorylineFlow();
    $('storyline-panel').classList.remove('hidden');
    setStage('storyline');
    $('storyline-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    toast('Storyline flow generated. Please review and approve before script generation.');
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

function renderStorylineFlow() {
  const flow = state.storylineFlow;
  if (!flow) return;
  const locked = state.storylineFlowApproved;

  // Summary row
  const leadChar = flow.leadCharacter?.name || 'Pico';
  $('storyline-summary-row').innerHTML = [
    ['AGE BAND', flow.ageBand],
    ['PLANNED DURATION', `${flow.targetDurationSeconds}s`],
    ['FLOW STEPS', flow.flowSteps?.length || 0],
    ['COMPANION CHARACTER', `${leadChar} (${flow.leadCharacter?.characterType || 'robot'})`],
  ]
    .map(([k, v]) => `<div class="summary-item"><span>${k}</span><strong>${escapeHtml(v)}</strong></div>`)
    .join('');

  $('flow-age-badge').textContent = `AGE ${flow.ageBand}`;
  $('flow-title-input').value = flow.title || '';
  $('flow-title-input').disabled = locked;
  $('flow-setting-input').value = flow.setting || '';
  $('flow-setting-input').disabled = locked;
  $('flow-premise-input').value = flow.narrativePremise || '';
  $('flow-premise-input').disabled = locked;

  // Lead character fields
  const char = flow.leadCharacter || {};
  $('flow-char-name-input').value = char.name || '';
  $('flow-char-name-input').disabled = locked;
  $('flow-char-type-input').value = char.characterType || 'robot';
  $('flow-char-type-input').disabled = locked;
  $('flow-char-role-input').value = char.role || '';
  $('flow-char-role-input').disabled = locked;

  // Mechanics card
  const mech = flow.gamificationElements || {};
  $('mechanics-details').innerHTML = `
    <div style="display:flex; flex-direction:column; gap:6px; font-size:12px;">
      <div><strong>Theme:</strong> ${escapeHtml(mech.gameTheme || 'Quest')}</div>
      <div><strong>Player Role:</strong> ${escapeHtml(mech.playerRole || 'Player')}</div>
      <div><strong>Challenge:</strong> ${escapeHtml(mech.challengeType || 'Observation')}</div>
      <div><strong>Hook:</strong> ${escapeHtml(mech.engagementHook || 'Solve mystery')}</div>
    </div>
  `;

  // Flow steps
  $('flow-steps-container').innerHTML = (flow.flowSteps || [])
    .map((step, idx) => {
      const actType = step.actType || 'intro';
      return `
      <div class="flow-step-card" data-step-idx="${idx}">
        <div class="flow-step-head">
          <div class="step-left">
            <span class="step-num-badge">STEP ${String(step.stepNumber).padStart(2, '0')}</span>
            <span class="act-badge ${actType}">${escapeHtml(actType.replace('_', ' '))}</span>
          </div>
          <span class="step-duration-chip">${Math.round(step.durationSeconds)} sec planned</span>
        </div>
        <div class="flow-step-fields">
          <label class="field">
            <span>Step Title</span>
            <input type="text" class="step-title-input" data-idx="${idx}" value="${escapeHtml(step.title)}" ${locked ? 'disabled' : ''} />
          </label>
          <label class="field">
            <span>Gamified Objective (What the child experiences)</span>
            <textarea class="step-objective-input" data-idx="${idx}" rows="2" ${locked ? 'disabled' : ''}>${escapeHtml(step.gamifiedObjective)}</textarea>
          </label>
        </div>
        <div class="flow-step-body">
          <div class="flow-meta-box">
            <span>Scientific Protocol Rule</span>
            <div>${escapeHtml(step.protocolRule || 'Preserve experiment condition')}</div>
          </div>
          <div class="flow-meta-box">
            <span>Visual Staging Description</span>
            <div>${escapeHtml(step.visualDescription || 'Visual staging description')}</div>
          </div>
        </div>
      </div>
    `;
    })
    .join('');

  // Attach live editing on inputs
  if (!locked) {
    $('flow-title-input').oninput = (e) => {
      state.storylineFlow.title = e.target.value;
    };
    $('flow-setting-input').oninput = (e) => {
      state.storylineFlow.setting = e.target.value;
    };
    $('flow-premise-input').oninput = (e) => {
      state.storylineFlow.narrativePremise = e.target.value;
    };
    $('flow-char-name-input').oninput = (e) => {
      if (!state.storylineFlow.leadCharacter) state.storylineFlow.leadCharacter = {};
      state.storylineFlow.leadCharacter.name = e.target.value;
    };
    $('flow-char-type-input').onchange = (e) => {
      if (!state.storylineFlow.leadCharacter) state.storylineFlow.leadCharacter = {};
      state.storylineFlow.leadCharacter.characterType = e.target.value;
    };
    $('flow-char-role-input').oninput = (e) => {
      if (!state.storylineFlow.leadCharacter) state.storylineFlow.leadCharacter = {};
      state.storylineFlow.leadCharacter.role = e.target.value;
    };
    qa('.step-title-input').forEach((input) => {
      input.oninput = (e) => {
        const idx = Number(e.target.dataset.idx);
        state.storylineFlow.flowSteps[idx].title = e.target.value;
      };
    });
    qa('.step-objective-input').forEach((input) => {
      input.oninput = (e) => {
        const idx = Number(e.target.dataset.idx);
        state.storylineFlow.flowSteps[idx].gamifiedObjective = e.target.value;
      };
    });
  }

  // Update button states & lock/unlock buttons
  if (locked) {
    $('approve-storyline').classList.add('hidden');
    $('unlock-storyline').classList.remove('hidden');
    $('save-storyline').disabled = true;
    $('generate-script-from-flow').disabled = false;
    $('storyline-gate-hint').innerHTML =
      '<strong>Storyline approved & locked.</strong> You can now generate the exact video script & dialogues.';
  } else {
    $('approve-storyline').classList.remove('hidden');
    $('unlock-storyline').classList.add('hidden');
    $('save-storyline').disabled = false;
    $('generate-script-from-flow').disabled = true;
    $('storyline-gate-hint').textContent =
      'Storyline flow must be approved before script & dialogues can be generated.';
  }
}

$('save-storyline').onclick = async () => {
  if (!state.runId) return;
  try {
    loading('Saving Storyline Edits', 'Validating storyline structure');
    const r = await api(`/api/runs/${state.runId}/storyline-flow`, {
      method: 'PUT',
      body: JSON.stringify({ storylineFlow: state.storylineFlow }),
    });
    state.storylineFlow = r.storylineFlow;
    renderStorylineFlow();
    toast('Storyline edits saved.');
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

$('approve-storyline').onclick = async () => {
  if (!state.runId) return;
  try {
    loading('Approving Storyline Flow', 'Locking gamified flow and unlocking script generation');
    const r = await api(`/api/runs/${state.runId}/approve-storyline`, {
      method: 'POST',
      body: JSON.stringify({ storylineFlow: state.storylineFlow }),
    });
    state.storylineFlow = r.storylineFlow;
    state.storylineFlowApproved = true;
    renderStorylineFlow();
    toast('Storyline flow approved! Script generation is now unlocked.');
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

$('unlock-storyline').onclick = async () => {
  if (!state.runId) return;
  try {
    await api(`/api/runs/${state.runId}/unlock-storyline`, { method: 'POST' });
    state.storylineFlowApproved = false;
    state.approved = false;
    renderStorylineFlow();
    $('review').classList.add('hidden');
    $('translation-panel').classList.add('hidden');
    $('voiceover').classList.add('hidden');
    $('dataset').classList.add('hidden');
    setStage('storyline');
    toast('Storyline unlocked for editing.');
  } catch (e) {
    toast(e.message, true);
  }
};

// --- STAGE 2: GENERATE SCRIPT & DIALOGUES FROM APPROVED STORYLINE ---
$('generate-script-from-flow').onclick = async () => {
  if (!state.runId) return;
  if (!state.storylineFlowApproved) {
    toast('Please approve the storyline flow first.', true);
    return;
  }
  try {
    loading('Generating Script & Dialogues', 'Writing scene dialogues directly from approved gamified storyline');
    const r = await api(`/api/runs/${state.runId}/generate-script`, { method: 'POST' });
    state.storyline = r.storyline;
    state.approved = false;
    renderStory();
    $('review').classList.remove('hidden');
    setStage('script');
    $('review').scrollIntoView({ behavior: 'smooth', block: 'start' });
    toast('Script and dialogues generated from approved storyline. Review and approve before translation.');
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

function renderStory() {
  const s = state.storyline;
  if (!s) return;
  $('story-summary').innerHTML = [
    ['SECTIONS', s.plannedSections?.length || 0],
    ['SCENES', s.scenes?.length || 0],
    ['LEAD CHARACTER', s.scenes?.[0]?.characterName || 'Pico'],
  ]
    .map(([k, v]) => `<div class="summary-item"><span>${k}</span><strong>${escapeHtml(v)}</strong></div>`)
    .join('');

  $('scene-list').innerHTML = s.scenes
    .map(
      (sc) => `
      <button class="scene-card ${sc.sceneOrder === state.selectedScene ? 'active' : ''}" data-order="${sc.sceneOrder}">
        <span class="scene-no">${String(sc.sceneOrder).padStart(2, '0')}</span>
        <span class="scene-copy"><small>${escapeHtml(sc.audioScript)}</small></span>
        <span class="scene-sec">${Math.round(sc.durationSeconds)}s</span>
      </button>`
    )
    .join('');

  qa('.scene-card').forEach((btn) => {
    btn.onclick = () => {
      state.selectedScene = Number(btn.dataset.order);
      renderStory();
    };
  });
  renderEditor();
}

function renderEditor() {
  const sc = state.storyline?.scenes?.find((x) => x.sceneOrder === state.selectedScene);
  if (!sc) return;
  const locked = state.approved;
  $('scene-editor').innerHTML = `
    <div class="editor-head">
      <div>
        <span class="eyebrow">SCENE ${String(sc.sceneOrder).padStart(2, '0')} · ${escapeHtml(sc.characterName)} (${escapeHtml(sc.characterState)})</span>
        <div class="editor-meta">
          <span class="mini-chip">${Number(sc.durationSeconds).toFixed(1)} sec planned</span>
          <span class="mini-chip">Asset: ${escapeHtml(sc.visualAssetTag)}</span>
        </div>
      </div>
      <span class="badge ${locked ? 'success' : ''}">${locked ? 'LOCKED' : 'EDITABLE'}</span>
    </div>
    <div class="editor-grid">
      <label class="field wide">
        <span>Spoken Narration & Dialogues (audioScript)</span>
        <textarea data-key="audioScript" rows="5" ${locked ? 'disabled' : ''}>${escapeHtml(sc.audioScript)}</textarea>
      </label>
    </div>
    <div class="readonly-note">Scene setting is fixed for continuity: ${escapeHtml(sc.setting || state.storyline.setting || 'the approved story setting')}.</div>
    ${
      sc.trial
        ? `<div class="readonly-note">Trial ${sc.trial.trialNumber} · Phase: ${escapeHtml(sc.trial.phase)} · Stimulus display: ${sc.trial.displayDurationSeconds}s · Response window: ${sc.trial.responseWindowSeconds}s · Missing: ${sc.trial.missingNumber}</div>`
        : '<div class="readonly-note">No trial metadata on this scene.</div>'
    }
  `;

  qa('#scene-editor [data-key]').forEach((el) => {
    el.oninput = () => {
      const key = el.dataset.key;
      sc[key] = el.value;
      sc.sourceText = el.value;
      const item = state.storyline.scenes.find((x) => x.sceneOrder === sc.sceneOrder);
      if (item) {
        item[key] = el.value;
        item.sourceText = el.value;
      }
    };
  });
}

$('save-script').onclick = async () => {
  if (!state.runId) return;
  try {
    loading('Saving Script Edits', 'Validating scene contract');
    const r = await api(`/api/runs/${state.runId}/storyline`, {
      method: 'PUT',
      body: JSON.stringify({ storyline: state.storyline }),
    });
    state.storyline = r.storyline;
    renderStory();
    toast('Script edits saved.');
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

$('approve').onclick = async () => {
  if (!state.runId) return;
  try {
    loading('Locking Approved Script', 'Recording final approved script for translation');
    const r = await api(`/api/runs/${state.runId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ storyline: state.storyline }),
    });
    state.storyline = r.storyline;
    state.approved = true;
    renderStory();

    $('approve').disabled = true;
    $('approve').classList.add('hidden');
    $('unlock').classList.remove('hidden');
    $('save-script').disabled = true;

    $('translation-panel').classList.remove('hidden');
    $('voiceover').classList.remove('hidden');
    $('translate').disabled = false;
    $('translate-state').textContent = 'Script approved. Choose Sarvam or BHASHINI translation.';
    setStage('translate');
    toast('Script & dialogues approved. Ready for translation.');
    $('translation-panel').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

$('unlock').onclick = async () => {
  if (!state.runId) return;
  try {
    await api(`/api/runs/${state.runId}/unlock-script`, { method: 'POST' });
    state.approved = false;
    $('approve').disabled = false;
    $('approve').classList.remove('hidden');
    $('unlock').classList.add('hidden');
    $('save-script').disabled = false;
    $('translate').disabled = true;
    $('make-voice').disabled = true;
    $('translation-panel').classList.add('hidden');
    $('voiceover').classList.add('hidden');
    $('dataset').classList.add('hidden');
    setStage('script');
    renderEditor();
    $('translate-state').textContent = 'Waiting for script approval.';
    toast('Script unlocked for editing.');
  } catch (e) {
    toast(e.message, true);
  }
};

// --- STAGE 3: TRANSLATION ---
qa('.translation-provider-card').forEach((card) => {
  card.onclick = () => {
    state.translationProvider = card.dataset.translationProvider;
    qa('.translation-provider-card').forEach((x) => x.classList.toggle('selected', x === card));
    const label = state.config?.translationProviders?.[state.translationProvider]?.label || state.translationProvider;
    $('translate-state').textContent = state.approved
      ? `Script approved. Ready to translate with ${label}.`
      : 'Waiting for script approval.';
  };
});

$('translate').onclick = async () => {
  try {
    const provider = state.translationProvider;
    const label =
      state.config?.translationProviders?.[provider]?.label ||
      (provider === 'bhashini' ? 'BHASHINI / ULCA' : 'Sarvam Translate');
    loading('Translating Approved Narration', `${label} · pause markers preserved`);
    const r = await api(`/api/runs/${state.runId}/translate`, {
      method: 'POST',
      body: JSON.stringify({ targetLanguage: $('language').value, provider }),
    });
    state.translated = r.storyline;
    renderTranslation();
    $('make-voice').disabled = false;
    $('voice-state').textContent = `Translation ready from ${label}. Choose TTS provider, voice and FPS.`;
    setStage('voice');
    toast(`Translation complete with ${label}.`);
    $('voiceover').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

function renderTranslation() {
  $('translation-preview').classList.remove('hidden');
  $('translation-preview').innerHTML = state.translated.scenes
    .map(
      (sc) => `
      <div class="translation-row">
        <span>${String(sc.sceneOrder).padStart(2, '0')}</span>
        <p>${escapeHtml(sc.translatedText)}</p>
      </div>`
    )
    .join('');
}

// --- STAGE 4: VOICEOVER ---
qa('.tts-provider-card').forEach((card) => {
  card.onclick = () => {
    state.provider = card.dataset.provider;
    qa('.tts-provider-card').forEach((x) => x.classList.toggle('selected', x === card));
    updateVoices();
  };
});

function updateVoices() {
  if (!state.config) return;
  const lang = $('language').value;
  const provider = state.config.ttsProviders[state.provider];
  const voices = provider?.voices?.[lang] || [];
  $('voice').innerHTML = voices
    .map((v) => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.label)}</option>`)
    .join('');
}

$('language').onchange = updateVoices;

$('make-voice').onclick = async () => {
  try {
    const provider = state.provider;
    loading(
      `Generating ${provider === 'azure' ? 'Azure' : 'Sarvam'} Voiceover`,
      'Synthesizing scene WAVs and computing timeline metadata'
    );
    const r = await api(`/api/runs/${state.runId}/voiceover`, {
      method: 'POST',
      body: JSON.stringify({ provider, voice: $('voice').value, fps: Number($('fps').value) }),
    });
    state.dataset = r;
    renderDataset();
    $('dataset').classList.remove('hidden');
    setStage('dataset');
    toast(`${provider === 'azure' ? 'Azure' : 'Sarvam'} voiceover complete.`);
    $('dataset').scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    toast(e.message, true);
  } finally {
    done();
  }
};

function renderDataset() {
  const d = state.dataset;
  $('download-json').href = `/api/runs/${state.runId}/dataset`;
  $('combined-audio').src = d.combinedAudioUrl;
  $('result-title').textContent = `${d.ttsProvider === 'azure' ? 'Azure Speech' : 'Sarvam Bulbul v3'} · ${d.voice}`;
  $('result-copy').textContent = `${d.sceneCount} scene WAVs + combined WAV · ${d.language} · ${d.fps} FPS timeline`;
  $('dataset-stats').innerHTML = [
    ['SCENES', d.sceneCount],
    ['AUDIO LENGTH', `${(d.audioTimelineDurationMs / 1000).toFixed(1)}s`],
    ['FPS', d.fps],
    ['DATASET', 'v' + d.datasetVersion],
  ]
    .map(([k, v]) => `<div class="stat"><span>${k}</span><strong>${escapeHtml(v)}</strong></div>`)
    .join('');

  $('dataset-body').innerHTML = d.scenes
    .map(
      (sc) => `
      <tr>
        <td>${String(sc.sceneOrder).padStart(2, '0')}</td>
        <td>${escapeHtml(sc.ttsProvider)}<br><small>${escapeHtml(sc.voice)}</small></td>
        <td><audio controls src="${escapeHtml(sc.audioUrl)}"></audio><br><small>${sc.audioDurationMs} ms</small></td>
        <td>${sc.startTimeMs} → ${sc.endTimeMs} ms</td>
        <td>${sc.startFrame} → ${sc.endFrameExclusive - 1}<br><small>${sc.totalFrames} frames</small></td>
      </tr>`
    )
    .join('');
}

init();
