import { AnnouncerProvider, ToastProvider, TooltipProvider } from '@/components';
import { IS_WEB_BUILD } from '@/lib/build';
import { NavigationProvider, type ScreenParamsMap } from './navigation';
import { URL_ROUTING, routeFromLocation, type Route } from './routes';
import { Shell } from './Shell';
import { ShellProvider } from './shell-state';
import { urlQuery, urlScreen } from './url-hints';
import { WorkspaceProvider } from './workspace';

// Веб-версия: экран — из адреса (`/app/sources`, решение Р-В4); подсказки `?screen=` мокапа
// в ней не действуют — экраны мокапа так не открыть. Мокап открывается на лендинге,
// расширение — на экране из подсказки (extension/lib/boot.tsx).
const initialRoute: Route = URL_ROUTING
  ? routeFromLocation()
  : { screen: urlScreen() ?? (IS_WEB_BUILD ? 'search' : 'landing'), params: {} };
const initialQuery = urlQuery();

/**
 * Текст из адреса (`?q=`). Расширение так передаёт выделенный текст — экран сразу ищет или
 * проверяет. В веб-версии текст только подставляется (решение Р-В6): чужая ссылка не должна
 * сама запускать поиск и тратить квоту.
 */
function initialParams(): ScreenParamsMap[Route['screen']] {
  const { screen, params } = initialRoute;
  if ((screen === 'search' || screen === 'ai-check') && initialQuery)
    return IS_WEB_BUILD ? { text: initialQuery } : { text: initialQuery, autoRun: true };
  return params;
}

/** Корень приложения: провайдеры и оболочка. */
export function App() {
  return (
    <ShellProvider>
      <TooltipProvider delayDuration={350} skipDelayDuration={200}>
        <AnnouncerProvider>
          <ToastProvider>
            <WorkspaceProvider>
              <NavigationProvider
                initial={initialRoute.screen}
                initialParams={initialParams()}
                urlRouting={URL_ROUTING}
              >
                <Shell />
              </NavigationProvider>
            </WorkspaceProvider>
          </ToastProvider>
        </AnnouncerProvider>
      </TooltipProvider>
    </ShellProvider>
  );
}
