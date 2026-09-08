import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { ApiClient, Capture } from '../api';
import { describeError } from '../core/problem';

/**
 * Voice, camera and file input for captures, usable on a day, a product or the inbox.
 *
 * - "Record" uses MediaRecorder (webm/opus in Chrome and Firefox, mp4 in Safari); the
 *   server converts and transcribes.
 * - "Take photo" opens the camera on phones (`capture="environment"`), a file dialog elsewhere.
 * - "Choose" accepts several images or audio files at once.
 * Each file is uploaded as its own capture with the given day or product.
 */
@Component({
  selector: 'v-capture-input',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cap" [class.compact]="compact()">
      @if (recording()) {
        <button type="button" class="v-btn danger rec" (click)="stopRecording()" aria-label="Stop recording">
          <span class="pulse" aria-hidden="true"></span> Stop · {{ elapsed() }}
        </button>
      } @else {
        <button type="button" class="v-btn" (click)="startRecording()" [disabled]="busy() || !canRecord" [title]="canRecord ? 'Record a voice note' : 'Recording is not available in this browser'">
          <span aria-hidden="true">🎙</span> Record
        </button>
      }
      <button type="button" class="v-btn" (click)="camera.click()" [disabled]="busy()"><span aria-hidden="true">📷</span> Take photo</button>
      <button type="button" class="v-btn" (click)="picker.click()" [disabled]="busy()"><span aria-hidden="true">🖼</span> Choose</button>
      <input #camera type="file" accept="image/*" capture="environment" hidden (change)="onFiles($event)" />
      <input #picker type="file" accept="image/*,audio/*" multiple hidden (change)="onFiles($event)" />
      @if (busy()) { <span class="v-small v-muted">Uploading…</span> }
      @if (notice(); as n) { <span class="v-small v-muted">{{ n }}</span> }
      @if (error(); as e) { <span class="v-small err">{{ e }}</span> }
    </div>
  `,
  styles: `
    .cap { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
    .cap.compact .v-btn { padding: 0.3rem 0.6rem; font-size: var(--v-fs-s); }
    .rec { font-variant-numeric: tabular-nums; }
    .pulse { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--v-bad); display: inline-block; animation: pulse 1s infinite; }
    .err { color: var(--v-bad); }
    @keyframes pulse { 50% { opacity: 0.3; } }
  `,
})
export class CaptureInput {
  private readonly api = inject(ApiClient);
  /** Day the captures belong to (ISO date); omit for the inbox. */
  readonly targetDate = input<string | null>(null);
  /** Product the captures are about (label photo, correction); omit for days. */
  readonly productId = input<number | null>(null);
  readonly compact = input(false);
  readonly uploaded = output<Capture>();

  readonly busy = signal(false);
  readonly recording = signal(false);
  readonly elapsed = signal('0:00');
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  readonly canRecord = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;

  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private ticker: ReturnType<typeof setInterval> | null = null;

  async startRecording(): Promise<void> {
    this.error.set(null);
    this.notice.set(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find((m) =>
        MediaRecorder.isTypeSupported(m),
      );
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      this.chunks = [];
      rec.ondataavailable = (e) => {
        if (e.data.size) this.chunks.push(e.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const type = rec.mimeType || 'audio/webm';
        const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm';
        const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        this.upload([new File(this.chunks, `voice-${stamp}.${ext}`, { type })]);
      };
      rec.start();
      this.recorder = rec;
      this.startedAt = Date.now();
      this.recording.set(true);
      this.elapsed.set('0:00');
      this.ticker = setInterval(() => {
        const s = Math.floor((Date.now() - this.startedAt) / 1000);
        this.elapsed.set(`${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`);
      }, 500);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : 'Microphone not available');
    }
  }

  stopRecording(): void {
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
    this.recording.set(false);
    this.recorder?.stop();
    this.recorder = null;
  }

  onFiles(ev: Event): void {
    const el = ev.target as HTMLInputElement;
    const files = Array.from(el.files ?? []);
    el.value = '';
    if (files.length) this.upload(files);
  }

  private upload(files: File[]): void {
    this.busy.set(true);
    this.error.set(null);
    this.notice.set(null);
    let pending = files.length;
    let duplicates = 0;
    const done = () => {
      if (--pending > 0) return;
      this.busy.set(false);
      if (duplicates) this.notice.set(duplicates === 1 ? 'Already captured (same content).' : `${duplicates} files were already captured.`);
    };
    for (const file of files) {
      const form = new FormData();
      form.append('file', file, file.name);
      const day = this.targetDate();
      const product = this.productId();
      if (product != null) form.append('product_id', String(product));
      else if (day) form.append('target_date', day);
      this.api.uploadCapture(form).subscribe({
        next: (c) => {
          if (c.created === false) duplicates++;
          else this.uploaded.emit(c);
          done();
        },
        error: (e: unknown) => {
          this.error.set(describeError(e));
          done();
        },
      });
    }
  }
}
