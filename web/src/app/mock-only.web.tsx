/**
 * Веб-версия: экранов мокапа нет (адреса `/app/landing`, `?screen=demo-page` их не откроют),
 * панели «Демо-сценарий» и имитации — тоже. Подменяет ./mock-only.tsx в сборке `web`.
 */
import type { ComponentType } from 'react';
import NotFoundScreen from '@/screens/not-found';
import type * as Mock from './mock-only';

export const subscribeDemo: typeof Mock.subscribeDemo = () => () => undefined;

export const DemoPanel: ComponentType = () => null;

export const HostPage: ComponentType = () => null;

/** Экран мокапа в веб-версии — «Такого раздела нет». */
const Missing = () => <NotFoundScreen params={{}} navKey={0} active />;

export const GalleryScreen: typeof Mock.GalleryScreen = Missing;

export const DemoPageScreen: typeof Mock.DemoPageScreen = Missing;

export const LandingScreen: typeof Mock.LandingScreen = Missing;
