import { AnnouncerProvider, ToastProvider, TooltipProvider } from '@/components';
import { NavigationProvider } from './navigation';
import { Shell } from './Shell';
import { ShellProvider } from './shell-state';
import { IS_WEB_BUILD } from '@/lib/build';
import { urlQuery, urlScreen } from './url-hints';

// Веб-версия открывается сразу на «Поиске», как расширение; мокап — на лендинге
const initialScreen = urlScreen() ?? (IS_WEB_BUILD ? 'search' : 'landing');
const initialQuery = urlQuery();

/** Корень приложения: провайдеры и оболочка. */
export function App() {
  return (
    <ShellProvider>
      <TooltipProvider delayDuration={350} skipDelayDuration={200}>
        <AnnouncerProvider>
          <ToastProvider>
            <NavigationProvider
              initial={initialScreen}
              initialParams={
                (initialScreen === 'search' || initialScreen === 'ai-check') && initialQuery
                  ? { text: initialQuery, autoRun: true }
                  : {}
              }
            >
              <Shell />
            </NavigationProvider>
          </ToastProvider>
        </AnnouncerProvider>
      </TooltipProvider>
    </ShellProvider>
  );
}
