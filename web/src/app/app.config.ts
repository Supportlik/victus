import { registerLocaleData } from '@angular/common';
import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import localeDe from '@angular/common/locales/de';
import localeEnGb from '@angular/common/locales/en-GB';
import { ApplicationConfig, LOCALE_ID, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideEchartsCore } from 'ngx-echarts';
import { routes } from './app.routes';
import { authInterceptor } from './core/auth/auth.interceptor';
import { storedLocale } from './core/format.service';

// Formatting data for the locales the settings offer. en-US is Angular's built-in default.
registerLocaleData(localeDe, 'de-DE');
registerLocaleData(localeEnGb, 'en-GB');

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withFetch(), withInterceptors([authInterceptor])),
    // LOCALE_ID is fixed for the life of the application, so it reads the mirrored choice
    // written by FormatService when the settings were last loaded (R69).
    { provide: LOCALE_ID, useFactory: storedLocale },
    // Angular Material 22 no longer needs @angular/animations. ECharts is loaded on demand
    // so the initial bundle stays small.
    provideEchartsCore({ echarts: () => import('echarts') }),
  ],
};
