import { Routes } from '@angular/router';
import { authGuard } from './core/auth/auth.guard';

const today = (): string => new Date().toISOString().slice(0, 10);

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./features/auth/login-page').then((m) => m.LoginPage) },
  {
    path: '',
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: () => `/days/${today()}` },
      { path: 'days', loadComponent: () => import('./features/days/days-page').then((m) => m.DaysPage) },
      { path: 'days/:date', loadComponent: () => import('./features/days/day-view').then((m) => m.DayView) },
      { path: 'drafts', loadComponent: () => import('./features/drafts/drafts-page').then((m) => m.DraftsPage) },
      { path: 'drafts/:date', loadComponent: () => import('./features/drafts/draft-approval').then((m) => m.DraftApproval) },
      { path: 'products', loadComponent: () => import('./features/products/products-page').then((m) => m.ProductsPage) },
      { path: 'products/review', loadComponent: () => import('./features/products/review-list').then((m) => m.ReviewList) },
      { path: 'products/new', loadComponent: () => import('./features/products/product-form').then((m) => m.ProductForm) },
      { path: 'products/:id', loadComponent: () => import('./features/products/product-detail').then((m) => m.ProductDetail) },
      { path: 'recipes', loadComponent: () => import('./features/recipes/recipes-page').then((m) => m.RecipesPage) },
      { path: 'recipes/:id', loadComponent: () => import('./features/recipes/recipe-detail').then((m) => m.RecipeDetail) },
      { path: 'weight', loadComponent: () => import('./features/weight/weight-page').then((m) => m.WeightPage) },
      { path: 'reports', loadComponent: () => import('./features/reports/reports-page').then((m) => m.ReportsPage) },
      { path: 'captures', loadComponent: () => import('./features/captures/captures-page').then((m) => m.CapturesPage) },
      { path: 'settings', loadComponent: () => import('./features/settings/settings-page').then((m) => m.SettingsPage) },
    ],
  },
  { path: '**', redirectTo: '' },
];
