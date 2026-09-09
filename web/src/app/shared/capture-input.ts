import {
  ChangeDetectionStrategy,
  Component,
  computed,
  ElementRef,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { ApiClient, Capture } from '../api';
import { Icon } from './icon';
import { I18nService } from '../core/i18n.service';
import { describeError } from '../core/problem';

interface Pending {
  file: File;
  url: string | null;
  kind: 'image' | 'audio' | 'other';
}

/**
 * One capture, in one form: a line of text, photos, a voice note, or any mix of them.
 *
 * There is no separate way to save text — text and files are the same capture, and the
 * single "Save capture" button sends whatever has been gathered (R64, R65):
 * - "Record" uses MediaRecorder (webm/opus in Chrome and Firefox, mp4 in Safari).
 * - "Take photo" opens the camera in place — full screen on a phone, with a camera switch
 *   and "another one" — and says why when no camera is reachable.
 * - "Choose" adds existing images or audio files.
 */
@Component({
  selector: 'v-capture-input',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    <div class="cap" [class.compact]="compact()">
      <textarea
        class="note"
        name="note"
        [rows]="compact() ? 2 : 3"
        [value]="note()"
        (input)="onNote($event)"
        [placeholder]="placeholder()"
        [disabled]="busy()"
      ></textarea>
      <div class="row">
      @if (recording()) {
        <button type="button" class="v-btn danger rec" (click)="stopRecording()" [attr.aria-label]="i18n.t('Stop recording')">
          <span class="pulse" aria-hidden="true"></span> {{ i18n.t('Stop') }} · {{ elapsed() }}
        </button>
      } @else {
        <button type="button" class="v-btn" (click)="startRecording()" [disabled]="busy() || !canRecord" [title]="i18n.t(canRecord ? 'Record a voice note' : 'Recording is not available in this browser')">
          <v-icon name="mic" [size]="17" /> {{ i18n.t('Record') }}
        </button>
      }
      <button type="button" class="v-btn" (click)="takePhoto()" [disabled]="busy() || cameraOpen()"><v-icon name="camera" [size]="17" /> {{ i18n.t('Take photo') }}</button>
      <button type="button" class="v-btn" (click)="picker.click()" [disabled]="busy()"><v-icon name="images" [size]="17" /> {{ i18n.t('Choose') }}</button>
      <input #picker type="file" accept="image/*,audio/*" multiple hidden (change)="onFiles($event)" />
      @if (busy()) { <span class="v-small v-muted">{{ i18n.t('Uploading…') }}</span> }
      @if (notice(); as n) { <span class="v-small v-muted">{{ n }}</span> }
      @if (error(); as e) {
        <span class="v-small err">{{ e }}</span>
        <button type="button" class="v-btn small quiet" (click)="picker.click()">{{ i18n.t('Choose a file instead') }}</button>
      }
      </div>

      @if (pending().length) {
        <div class="tray">
          <ul class="items">
            @for (p of pending(); track p.file.name + p.file.size) {
              <li>
                @if (p.kind === 'image' && p.url) { <img [src]="p.url" alt="" /> }
                @else { <span class="glyph" aria-hidden="true">{{ p.kind === 'audio' ? '🎙' : '📄' }}</span> }
                <span class="name">{{ p.file.name }}</span>
                <button type="button" class="v-btn quiet small danger" (click)="drop(p)" [attr.aria-label]="i18n.t('Remove')">✕</button>
              </li>
            }
          </ul>
        </div>
      }

      <div class="v-actions">
        <button type="button" class="v-btn primary" (click)="submit()" [disabled]="busy() || !hasContent()">
          {{ saveLabel() }}
        </button>
        @if (hasContent()) {
          <button type="button" class="v-btn quiet" (click)="clear()" [disabled]="busy()">{{ i18n.t('Discard') }}</button>
        }
      </div>
    </div>

    @if (cameraOpen()) {
      <div class="cam" role="dialog" [attr.aria-label]="i18n.t('Camera')">
        <div class="bar">
          <button type="button" class="v-btn primary" (click)="shoot(false)">{{ i18n.t('Take the picture') }}</button>
          <button type="button" class="v-btn" (click)="shoot(true)">{{ i18n.t('Take another one') }}</button>
          @if (canSwitch()) { <button type="button" class="v-btn" (click)="switchCamera()">{{ i18n.t('Switch camera') }}</button> }
          <span class="shots">{{ i18n.t('{n} taken', { n: pending().length }) }}</span>
          <button type="button" class="v-btn quiet" (click)="closeCamera()">{{ i18n.t('Done') }}</button>
        </div>
        <video #preview autoplay playsinline muted></video>
      </div>
    }
  `,
  styles: `
    .cap { display: grid; gap: 0.5rem; }
    .row { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; }
    .note { width: 100%; box-sizing: border-box; padding: 0.5rem; border: 1px solid var(--v-line-strong); border-radius: var(--v-radius); background: var(--v-surface); color: inherit; font: inherit; resize: vertical; }
    .note:focus-visible { outline: 2px solid var(--v-primary); outline-offset: 1px; }
    .cap.compact .note { font-size: var(--v-fs-s); }
    .cap.compact .v-btn { padding: 0.3rem 0.6rem; font-size: var(--v-fs-s); }
    .rec { font-variant-numeric: tabular-nums; }
    .pulse { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--v-bad); display: inline-block; animation: pulse 1s infinite; }
    .err { color: var(--v-bad); }

    .tray { display: grid; gap: 0.5rem; padding: 0.5rem; border: 1px dashed var(--v-line-strong); border-radius: var(--v-radius-l); }
    .items { list-style: none; margin: 0; padding: 0; display: flex; gap: 0.5rem; flex-wrap: wrap; }
    .items li { display: flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.4rem; border: 1px solid var(--v-line); border-radius: var(--v-radius); background: var(--v-surface); }
    .items img { width: 3rem; height: 3rem; object-fit: cover; border-radius: var(--v-radius); }
    .items .name { max-width: 9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--v-fs-xs); color: var(--v-ink-2); }
    .items .glyph { font-size: 1.2rem; }

    /* Full screen on a phone; the buttons stay above the picture and always visible. */
    .cam { position: fixed; inset: 0; z-index: 50; background: #000; display: grid; grid-template-rows: auto 1fr; }
    .cam .bar { display: flex; gap: 0.4rem; flex-wrap: wrap; align-items: center; padding: 0.6rem; background: var(--v-surface); border-bottom: 1px solid var(--v-line); }
    .cam .shots { margin-left: auto; font-size: var(--v-fs-s); color: var(--v-ink-2); }
    .cam video { width: 100%; height: 100%; object-fit: contain; background: #000; }

    @keyframes pulse { 50% { opacity: 0.3; } }
  `,
})
export class CaptureInput {
  private readonly api = inject(ApiClient);
  readonly i18n = inject(I18nService);
  /** Day the captures belong to (ISO date); omit for the inbox. */
  readonly targetDate = input<string | null>(null);
  /** Product the captures are about (label photo, correction); omit for days. */
  readonly productId = input<number | null>(null);
  readonly compact = input(false);
  /** Hint in the empty text box; the wording differs per screen. */
  readonly placeholder = input('What did you eat? You can also add photos or a voice note.');
  readonly uploaded = output<Capture>();

  readonly busy = signal(false);
  readonly recording = signal(false);
  readonly elapsed = signal('0:00');
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);
  readonly pending = signal<Pending[]>([]);
  readonly note = signal('');
  /** Nothing is sent while the form is empty — text alone is a capture, files alone too. */
  readonly hasContent = computed(() => !!this.note().trim() || this.pending().length > 0);
  readonly saveLabel = computed(() => {
    const files = this.pending().length;
    if (!files) return this.i18n.t('Save capture');
    return this.i18n.t(files === 1 ? 'Save capture ({n} file)' : 'Save capture ({n} files)', {
      n: files,
    });
  });
  readonly canRecord = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  readonly cameraOpen = signal(false);
  readonly canSwitch = signal(false);

  private readonly preview = viewChild<ElementRef<HTMLVideoElement>>('preview');
  private cameraStream: MediaStream | null = null;
  private facing: 'environment' | 'user' = 'environment';
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private ticker: ReturnType<typeof setInterval> | null = null;

  // ── voice ────────────────────────────────────────────────────────────────

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
        this.add(new File(this.chunks, `voice-${this.stamp()}.${ext}`, { type }));
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
      this.error.set(this.mediaMessage(e, 'Microphone'));
    }
  }

  stopRecording(): void {
    if (this.ticker) clearInterval(this.ticker);
    this.ticker = null;
    this.recording.set(false);
    this.recorder?.stop();
    this.recorder = null;
  }

  // ── camera ───────────────────────────────────────────────────────────────

  async takePhoto(): Promise<void> {
    this.error.set(null);
    this.notice.set(null);
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      this.error.set(
        `The camera needs a secure connection. This page is ${location.origin}; open it over https or on localhost.`,
      );
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      this.error.set('This browser exposes no camera API. Update it, or open the page over https.');
      return;
    }
    await this.openCamera();
  }

  /**
   * Ask for the camera. Desktops have no front/back camera and some drivers reject
   * every constraint they do not know, so a failed request is retried bare.
   */
  private async grabCamera(): Promise<MediaStream> {
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: this.facing }, width: { ideal: 1600 } },
        audio: false,
      });
    } catch (e) {
      const name = e instanceof Error ? e.name : '';
      if (name === 'NotAllowedError' || name === 'SecurityError') throw e;
      return await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    }
  }

  private async openCamera(): Promise<void> {
    try {
      this.cameraStream = await this.grabCamera();
      this.cameraOpen.set(true);
      void this.detectCameras();
      // the <video> exists only once the dialog is rendered
      setTimeout(() => {
        const el = this.preview()?.nativeElement;
        if (el && this.cameraStream) {
          el.srcObject = this.cameraStream;
          void el.play().catch(() => undefined);
        }
      });
    } catch (e) {
      this.cameraOpen.set(false);
      this.error.set(this.mediaMessage(e, 'Camera'));
    }
  }

  private async detectCameras(): Promise<void> {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      this.canSwitch.set(devices.filter((d) => d.kind === 'videoinput').length > 1);
    } catch {
      this.canSwitch.set(false);
    }
  }

  async switchCamera(): Promise<void> {
    this.facing = this.facing === 'environment' ? 'user' : 'environment';
    this.stopStream();
    await this.openCamera();
  }

  /** Take a picture; `again` keeps the camera open for the next one. */
  shoot(again: boolean): void {
    const el = this.preview()?.nativeElement;
    if (!el || !el.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = el.videoWidth;
    canvas.height = el.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      this.error.set('This browser cannot take the picture; choose a file instead.');
      this.closeCamera();
      return;
    }
    ctx.drawImage(el, 0, 0, canvas.width, canvas.height);
    const stamp = this.stamp();
    canvas.toBlob(
      (blob) => {
        if (blob) this.add(new File([blob], `photo-${stamp}.jpg`, { type: 'image/jpeg' }));
        if (!again) this.closeCamera();
      },
      'image/jpeg',
      0.92,
    );
  }

  closeCamera(): void {
    this.stopStream();
    this.cameraOpen.set(false);
  }

  private stopStream(): void {
    this.cameraStream?.getTracks().forEach((t) => t.stop());
    this.cameraStream = null;
  }

  private mediaMessage(e: unknown, what: string): string {
    const name = e instanceof Error ? e.name : '';
    if (name === 'NotAllowedError')
      return `${what} blocked. Allow it for this site in the browser, and on Windows check Settings › Privacy › ${what}.`;
    if (name === 'NotFoundError' || name === 'OverconstrainedError') return `No ${what.toLowerCase()} found on this device.`;
    if (name === 'NotReadableError') return `The ${what.toLowerCase()} is in use by another program.`;
    return `${what} not available${e instanceof Error && e.message ? `: ${e.message}` : ''}.`;
  }

  // ── the tray: everything here goes up as one capture ─────────────────────

  onFiles(ev: Event): void {
    const el = ev.target as HTMLInputElement;
    const files = Array.from(el.files ?? []);
    el.value = '';
    files.forEach((f) => this.add(f));
  }

  private add(file: File): void {
    const kind = file.type.startsWith('image/') ? 'image' : file.type.startsWith('audio/') ? 'audio' : 'other';
    const url = kind === 'image' ? URL.createObjectURL(file) : null;
    this.pending.update((list) => [...list, { file, url, kind }]);
  }

  onNote(ev: Event): void {
    this.note.set((ev.target as HTMLTextAreaElement).value);
  }

  drop(p: Pending): void {
    if (p.url) URL.revokeObjectURL(p.url);
    this.pending.update((list) => list.filter((x) => x !== p));
  }

  clear(): void {
    this.pending().forEach((p) => p.url && URL.revokeObjectURL(p.url));
    this.pending.set([]);
    this.note.set('');
  }

  /** Upload the text and every file as one capture. */
  submit(): void {
    if (!this.hasContent()) return;
    const form = new FormData();
    for (const p of this.pending()) form.append('file', p.file, p.file.name);
    const text = this.note().trim();
    if (text) form.append('text', text);
    const day = this.targetDate();
    const product = this.productId();
    if (product != null) form.append('product_id', String(product));
    else if (day) form.append('target_date', day);

    this.busy.set(true);
    this.error.set(null);
    this.notice.set(null);
    this.api.uploadCapture(form).subscribe({
      next: (c) => {
        if (c.created === false) this.notice.set('Already captured (same content).');
        else this.uploaded.emit(c);
        this.clear();
        this.busy.set(false);
      },
      error: (e: unknown) => {
        this.error.set(describeError(e));
        this.busy.set(false);
      },
    });
  }

  private stamp(): string {
    return new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  }
}
