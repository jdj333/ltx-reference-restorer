import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function waitForJob(request: APIRequestContext, id: string) {
  await expect.poll(async () => (await (await request.get(`/api/jobs/${id}`)).json()).state,
    { timeout: 45_000, message: 'The real background worker should complete the FFmpeg baseline' }).toBe('succeeded');
  return (await (await request.get(`/api/jobs/${id}`)).json());
}

async function browse(page: Page, kind: 'video' | 'image', filename: string) {
  await page.getByRole('button', { name: kind === 'video' ? 'Browse local videos' : 'Browse local images', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: `Choose a local ${kind}` });
  await dialog.getByRole('button', { name: 'media', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Up one folder' })).toBeDisabled();
  await dialog.getByRole('button', { name: new RegExp(filename.replace('.', '\\.')) }).click();
  await expect(dialog).toBeHidden();
}

test('readiness, idempotent synthetic demo, synchronized comparison and durable review', async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', { name: 'Setup & status 06' }).click();
  await expect(page.getByRole('heading', { name: 'Setup & status', exact: true })).toBeVisible();
  await expect(page.getByText('Baseline tools ready', { exact: true })).toBeVisible();
  await expect.poll(async () => ['idle', 'running'].includes((await (await request.get('/api/system/status')).json()).worker.state)).toBe(true);
  await expect(page.getByText('LTX backend blocked', { exact: true })).toBeVisible();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download safe diagnostics' }).click();
  const download = await downloaded;
  expect(download.suggestedFilename()).toBe('ltx-restorer-diagnostics.json');
  const text = await readFile((await download.path())!, 'utf8');
  const diagnostics = JSON.parse(text);
  expect(diagnostics.baseline_ready).toBe(true);
  for (const forbidden of ['/Users/', '/home/', '/private/', '/tmp/', 'http://', 'comfy_url', 'project_id', 'access_token']) expect(text).not.toContain(forbidden);

  const demoResponse = page.waitForResponse(response => response.url().endsWith('/api/demo') && response.request().method() === 'POST');
  await page.getByRole('button', { name: /^(Try|Open) synthetic demo$/ }).click();
  const demo = await (await demoResponse).json();
  await expect(page.getByLabel('Open project')).toHaveValue(demo.project_id);
  const rendered = await waitForJob(request, demo.job_id);
  expect(rendered.backend).toBe('baseline');
  expect(rendered.provenance.technical_checks.timing_passed).toBe(true);
  expect(rendered.provenance.output_metadata.frame_count).toBe(24);
  const reopened = await (await request.post('/api/demo', { data: {} })).json();
  expect(reopened.reused).toBe(true);
  expect(reopened.job_id).toBe(demo.job_id);

  await page.getByRole('button', { name: 'Compare & review 05' }).click();
  await expect(page.getByText(/Baseline upscale · no actor reference conditioning/)).toBeVisible();
  const comparison = page.getByRole('group', { name: /^Synchronized comparison\./ });
  await expect.poll(async () => comparison.locator('video').evaluateAll(videos => videos.every(video => (video as HTMLVideoElement).readyState >= 2))).toBe(true);
  await page.getByRole('button', { name: 'Next comparison frame', exact: true }).click();
  await expect.poll(async () => Number(await page.getByLabel('Synchronized comparison playhead').inputValue())).toBeCloseTo(1 / 12, 3);
  await comparison.focus();
  await comparison.press('ArrowRight');
  await expect.poll(async () => Number(await page.getByLabel('Synchronized comparison playhead').inputValue())).toBeCloseTo(2 / 12, 3);
  await expect.poll(async () => comparison.locator('video').evaluateAll(videos => {
    const [a, b] = videos as HTMLVideoElement[];
    return Math.abs(a.currentTime - b.currentTime);
  })).toBeLessThan(1 / 12);
  await comparison.press('Space');
  await expect(page.getByRole('button', { name: 'Pause synchronized playback' })).toBeVisible();
  await comparison.press('Space');
  await expect(page.getByRole('button', { name: 'Play synchronized comparison' })).toBeVisible();
  await page.getByRole('button', { name: 'Overlay', exact: true }).click();
  await expect(page.getByLabel('Output overlay opacity')).toBeVisible();
  await page.getByLabel('Output overlay opacity').fill('0.25');
  await page.getByRole('button', { name: 'Side by side', exact: true }).click();
  const note = `AUTOMATED ${info.project.name} SYNTHETIC REVIEW PERSISTENCE TEST; no human fidelity approval.`;
  await page.getByRole('textbox', { name: /^Review notes/ }).fill(note);
  await page.getByRole('button', { name: 'Needs revision', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Review saved');
  await page.reload();
  await page.getByRole('button', { name: 'Compare & review 05' }).click();
  await expect(page.getByRole('textbox', { name: /^Review notes/ })).toHaveValue(note);
  expect((await (await request.get(`/api/jobs/${demo.job_id}`)).json()).provenance.output_sha256).toBe(rendered.provenance.output_sha256);
  expect(errors).toEqual([]);
});

test('keyboard dialogs, scoped file selection, visual reference crop and unsaved setup protection', async ({ page, request }, info) => {
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Create project', exact: true });
  await trigger.click();
  const modal = page.getByRole('dialog', { name: 'Create a project' });
  await expect(modal).toBeVisible();
  for (let i = 0; i < 7; i++) {
    await page.keyboard.press('Tab');
    await expect.poll(async () => modal.evaluate(dialog => dialog.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(modal).toBeHidden();
  await expect(trigger).toBeFocused();
  await trigger.click();
  const projectName = `Synthetic manual workflow — ${info.project.name}`;
  await page.getByRole('textbox', { name: 'Project name', exact: true }).fill(projectName);
  const created = page.waitForResponse(response => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
  await modal.getByRole('button', { name: 'Create project', exact: true }).click();
  const project = await (await created).json();
  await expect(page.getByLabel('Open project')).toHaveValue(project.id);
  await page.getByRole('button', { name: 'Sources & shots 01' }).click();
  await browse(page, 'video', 'synthetic-source.mp4');
  await page.getByRole('button', { name: 'Import video', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'synthetic-source.mp4', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Shot name', exact: true }).fill('Synthetic crop and guide');
  await page.getByRole('button', { name: 'Create shot', exact: true }).click();
  await page.getByLabel('Face region x', { exact: true }).fill('120');
  await page.getByLabel('Face region y', { exact: true }).fill('20');
  await page.getByLabel('Face region width', { exact: true }).fill('80');
  await page.getByLabel('Face region height', { exact: true }).fill('110');
  await expect(page.getByRole('button', { name: 'Save setup · unsaved changes' })).toBeVisible();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Actor library 02' }).click();
  await expect(page.getByRole('heading', { name: 'Shot setup', exact: true })).toBeVisible();
  let releaseSave!: () => void;
  let notifyHeld!: () => void;
  const saveGate = new Promise<void>(resolve => { releaseSave = resolve; });
  const saveHeld = new Promise<void>(resolve => { notifyHeld = resolve; });
  await page.route('**/api/shots/*', async route => {
    if (route.request().method() === 'PATCH') { notifyHeld(); await saveGate; }
    await route.continue();
  });
  await page.getByRole('button', { name: 'Save setup · unsaved changes' }).click();
  await saveHeld;
  try {
    await expect(page.getByLabel('Face region x', { exact: true })).toBeDisabled();
    await expect(page.getByRole('combobox', { name: 'Assigned actor', exact: true })).toBeDisabled();
    await expect(page.getByRole('combobox', { name: 'Render backend', exact: true })).toBeDisabled();
  } finally { releaseSave(); }
  await expect(page.getByRole('button', { name: 'Save setup', exact: true })).toBeEnabled();
  await page.unroute('**/api/shots/*');
  await page.getByLabel('Face region x', { exact: true }).fill('121');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Actor library 02' }).click();
  await expect(page.getByRole('heading', { name: 'Shot setup', exact: true })).toBeVisible();
  await page.getByLabel('Face region x', { exact: true }).fill('120');
  await expect(page.getByRole('button', { name: 'Save setup', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Actor library 02' }).click();
  await page.getByRole('textbox', { name: 'Add an actor', exact: true }).fill('Synthetic test actor');
  await page.getByRole('button', { name: 'Add actor', exact: true }).click();
  await page.getByRole('button', { name: 'Add reference', exact: true }).click();
  await browse(page, 'image', 'synthetic-reference.png');
  await page.getByRole('checkbox', { name: 'Crop this reference image' }).check();
  const crop = page.getByRole('img', { name: 'Reference crop preview', exact: true });
  await expect(page.getByText('Native image: 320 × 180 px', { exact: false })).toBeVisible();
  await crop.scrollIntoViewIfNeeded();
  const box = (await crop.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.375, box.y + box.height / 9);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.625, box.y + box.height * 13 / 18, { steps: 8 });
  await page.mouse.up();
  // Browser pointer coordinates are quantized to display pixels. Check the
  // visual selection within one native pixel, then exercise exact entry too.
  for (const [key, value] of Object.entries({ x: 120, y: 20, width: 80, height: 110 })) {
    const input = page.getByLabel(`Reference crop ${key}`, { exact: true });
    expect(Math.abs(Number(await input.inputValue()) - value)).toBeLessThanOrEqual(1);
    await input.fill(String(value));
    await expect(input).toHaveValue(String(value));
  }
  await page.getByRole('combobox', { name: 'Provenance', exact: true }).selectOption('generated_reconstruction');
  await page.getByRole('button', { name: 'Import reference', exact: true }).click();
  const approval = page.getByRole('combobox', { name: /^Approval for reference/ });
  await expect(approval).toHaveValue('pending');
  await approval.selectOption('approved');
  await expect(approval).toHaveValue('approved');
  await page.getByRole('button', { name: 'Shot setup 03' }).click();
  await page.getByRole('combobox', { name: 'Assigned actor', exact: true }).selectOption({ label: 'Synthetic test actor' });
  await page.getByRole('checkbox', { name: /actor reference/ }).check();
  await page.getByRole('button', { name: 'Prepare guide', exact: true }).click();
  await expect(page.getByText('PLACEMENT PREVIEW', { exact: true })).toBeVisible();
  const queued = page.waitForResponse(response => /\/api\/shots\/[^/]+\/jobs$/.test(response.url()) && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Queue baseline upscale', exact: true }).click();
  const job = await (await queued).json();
  const rendered = await waitForJob(request, job.id);
  expect(rendered.provenance.references[0].provenance).toBe('generated_reconstruction');
  expect(rendered.provenance.references[0].crop).toEqual([120, 20, 80, 110]);
  expect(rendered.provenance.references[0].width).toBe(80);
  expect(rendered.provenance.references[0].height).toBe(110);
  expect(rendered.provenance.technical_checks.timing_passed).toBe(true);
  expect(rendered.provenance.conditioning_consumed).toBe(false);
  const detail = await (await request.get(`/api/projects/${project.id}`)).json();
  expect(detail.shots[0].setup.keyframes[0]).toEqual({ frame: 0, x: 120, y: 20, width: 80, height: 110 });
});

test('switching projects clears media drafts and hides old data while the next workspace loads', async ({ page, request }, info) => {
  const a = await (await request.post('/api/projects', { data: { name: `Draft isolation A — ${info.project.name}` } })).json();
  const b = await (await request.post('/api/projects', { data: { name: `Draft isolation B — ${info.project.name}` } })).json();
  for (const project of [a, b]) await request.post(`/api/projects/${project.id}/actors`, { data: { name: 'Synthetic isolation actor' } });
  await page.goto('/');
  await page.getByLabel('Open project').selectOption(a.id);
  await page.getByRole('button', { name: 'Sources & shots 01' }).click();
  await browse(page, 'video', 'synthetic-source.mp4');
  await expect(page.getByText('synthetic-source.mp4', { exact: true })).toBeVisible();
  let releaseLoad!: () => void;
  let notifyLoad!: () => void;
  const gate = new Promise<void>(resolve => { releaseLoad = resolve; });
  const held = new Promise<void>(resolve => { notifyLoad = resolve; });
  const pattern = `**/api/projects/${b.id}`;
  await page.route(pattern, async route => { notifyLoad(); await gate; await route.continue(); });
  await page.getByLabel('Open project').selectOption(b.id);
  await held;
  try { await expect(page.getByText('synthetic-source.mp4', { exact: true })).toBeHidden(); }
  finally { releaseLoad(); }
  await expect(page.getByText('No video selected', { exact: true })).toBeVisible();
  await page.unroute(pattern);
  await page.getByLabel('Open project').selectOption(a.id);
  await expect(page.getByText('No video selected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Actor library 02' }).click();
  await page.getByRole('button', { name: 'Add reference', exact: true }).click();
  await browse(page, 'image', 'synthetic-reference.png');
  await expect(page.getByText('synthetic-reference.png', { exact: true })).toBeVisible();
  await page.getByLabel('Open project').selectOption(b.id);
  await expect(page.getByText('synthetic-reference.png', { exact: true })).toBeHidden();
  await page.getByRole('button', { name: 'Add reference', exact: true }).click();
  await expect(page.getByText('No image selected', { exact: true })).toBeVisible();
  for (const project of [a, b]) {
    const detail = await (await request.get(`/api/projects/${project.id}`)).json();
    expect(detail.sources).toHaveLength(0);
    expect(detail.references).toHaveLength(0);
  }
});
