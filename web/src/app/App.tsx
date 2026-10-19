import { AnnouncerProvider, ToastProvider, TooltipProvider } from '@/components';
import { NavigationProvider } from './navigation';
import { Shell } from './Shell';
import { ShellProvider } from './shell-state';
import { urlQuery, urlScreen } from './url-hints';

const initialScreen = urlScreen() ?? 'landing';
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
                initialScreen === 'search' && initialQuery
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
