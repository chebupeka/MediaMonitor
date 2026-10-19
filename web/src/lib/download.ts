/**
 * Сохранить файл, собранный на странице, — как обычное скачивание: браузер кладёт его
 * в «Загрузки» или спрашивает, куда сохранить. Работает и на сайте, и в боковой панели
 * расширения, без разрешения downloads.
 */
export function saveFile(file: Blob, fileName: string): void {
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  // Браузеру нужно время, чтобы начать скачивание, — адрес освобождаем позже
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
