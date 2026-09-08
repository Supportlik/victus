import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { DayStatus } from '../api';

const LABEL: Record<DayStatus, string> = { draft: 'Draft', open: 'Open', closed: 'Closed' };

@Component({
  selector: 'v-status-tag',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="v-tag" [class]="status()">{{ label }}</span>`,
})
export class StatusTag {
  readonly status = input.required<DayStatus>();
  get label(): string {
    return LABEL[this.status()];
  }
}
