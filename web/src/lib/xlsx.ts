/**
 * XLSX без зависимостей: книга из нескольких листов с текстом, числами и ссылками.
 *
 * XLSX — это ZIP с XML-файлами (ECMA-376). Пишем минимум, который открывают Excel,
 * LibreOffice, «МойОфис» и Р7: строки встроены в ячейки (inlineStr), без общей таблицы
 * строк; ZIP без сжатия (метод store) — так не нужен deflate, а подборка весит немного.
 * Формул нет (НТ-10): текст, который начинается с «=», остаётся текстом.
 */

export type XlsxCell = string | number | null;

export interface XlsxSheet {
  /** Имя листа: до 31 знака, без []:*?/\ */
  name: string;
  rows: XlsxCell[][];
  /** Ширина колонок в знаках */
  widths?: number[];
  /** Первая строка — шапка: жирная, закреплена при прокрутке, с автофильтром */
  header?: boolean;
  /** Номера колонок (с нуля), где значения — ссылки: в файле они кликабельные */
  linkColumns?: number[];
}

export const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

/** Excel не держит в ячейке больше 32 767 знаков */
const MAX_CELL_TEXT = 32_767;

const NS_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main';
const NS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const NS_PKG_REL = 'http://schemas.openxmlformats.org/package/2006/relationships';
const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';

/** Стили ячеек — номера в cellXfs (styles.xml ниже) */
const STYLE = { text: 2, header: 1, link: 3, number: 4 } as const;

export function buildXlsx(sheets: XlsxSheet[]): Blob {
  const names = uniqueSheetNames(sheets.map((s) => s.name));
  const files: { name: string; text: string }[] = [
    { name: '[Content_Types].xml', text: contentTypes(sheets.length) },
    {
      name: '_rels/.rels',
      text:
        `${XML_HEAD}<Relationships xmlns="${NS_PKG_REL}">` +
        `<Relationship Id="rId1" Type="${NS_REL}/officeDocument" Target="xl/workbook.xml"/>` +
        `</Relationships>`,
    },
    { name: 'xl/workbook.xml', text: workbook(sheets, names) },
    { name: 'xl/_rels/workbook.xml.rels', text: workbookRels(sheets.length) },
    { name: 'xl/styles.xml', text: STYLES },
  ];
  sheets.forEach((sheet, i) => {
    const { xml, links } = worksheet(sheet, i === 0);
    files.push({ name: `xl/worksheets/sheet${i + 1}.xml`, text: xml });
    if (links.length > 0)
      files.push({
        name: `xl/worksheets/_rels/sheet${i + 1}.xml.rels`,
        text:
          `${XML_HEAD}<Relationships xmlns="${NS_PKG_REL}">` +
          links
            .map(
              (url, n) =>
                `<Relationship Id="rId${n + 1}" Type="${NS_REL}/hyperlink" Target="${escapeXml(url)}" TargetMode="External"/>`,
            )
            .join('') +
          `</Relationships>`,
      });
  });
  const encoder = new TextEncoder();
  const bytes = zipStore(files.map((f) => ({ name: f.name, data: encoder.encode(f.text) })));
  return new Blob([bytes], { type: XLSX_MIME });
}

// ---------------------------------------------------------------- части книги

function contentTypes(sheetCount: number): string {
  const sheets = Array.from(
    { length: sheetCount },
    (_, i) =>
      `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`,
  ).join('');
  return (
    `${XML_HEAD}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
    `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>` +
    `<Default Extension="xml" ContentType="application/xml"/>` +
    `<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>` +
    `<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>` +
    sheets +
    `</Types>`
  );
}

function workbook(sheets: XlsxSheet[], names: string[]): string {
  const list = names
    .map((name, i) => `<sheet name="${escapeXml(name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`)
    .join('');
  // Автофильтр Excel ищет по скрытому имени _FilterDatabase у каждого листа с шапкой
  const filters = sheets
    .map((sheet, i) => {
      if (!sheet.header || sheet.rows.length === 0) return '';
      const quoted = `'${(names[i] ?? '').replace(/'/g, "''")}'`;
      const last = `$${columnName(columnCount(sheet) - 1)}$${sheet.rows.length}`;
      return `<definedName name="_xlnm._FilterDatabase" localSheetId="${i}" hidden="1">${escapeXml(`${quoted}!$A$1:${last}`)}</definedName>`;
    })
    .join('');
  return (
    `${XML_HEAD}<workbook xmlns="${NS_MAIN}" xmlns:r="${NS_REL}">` +
    `<bookViews><workbookView activeTab="0"/></bookViews>` +
    `<sheets>${list}</sheets>` +
    (filters ? `<definedNames>${filters}</definedNames>` : '') +
    `</workbook>`
  );
}

function workbookRels(sheetCount: number): string {
  const sheets = Array.from(
    { length: sheetCount },
    (_, i) =>
      `<Relationship Id="rId${i + 1}" Type="${NS_REL}/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`,
  ).join('');
  return (
    `${XML_HEAD}<Relationships xmlns="${NS_PKG_REL}">${sheets}` +
    `<Relationship Id="rId${sheetCount + 1}" Type="${NS_REL}/styles" Target="styles.xml"/>` +
    `</Relationships>`
  );
}

/** 0 — обычный; 1 — шапка; 2 — текст с переносом; 3 — ссылка; 4 — число */
const STYLES =
  `${XML_HEAD}<styleSheet xmlns="${NS_MAIN}">` +
  `<fonts count="3">` +
  `<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>` +
  `<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>` +
  `<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/><family val="2"/></font>` +
  `</fonts>` +
  `<fills count="3">` +
  `<fill><patternFill patternType="none"/></fill>` +
  `<fill><patternFill patternType="gray125"/></fill>` +
  `<fill><patternFill patternType="solid"><fgColor rgb="FFEDEFF3"/><bgColor indexed="64"/></patternFill></fill>` +
  `</fills>` +
  `<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>` +
  `<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>` +
  `<cellXfs count="5">` +
  `<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>` +
  `<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>` +
  `<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>` +
  `<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="top"/></xf>` +
  `<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top"/></xf>` +
  `</cellXfs>` +
  `<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>` +
  `</styleSheet>`;

function worksheet(sheet: XlsxSheet, selected: boolean): { xml: string; links: string[] } {
  const cols = columnCount(sheet);
  const links: string[] = [];
  const linkRefs: string[] = [];
  const linkColumns = new Set(sheet.linkColumns ?? []);

  const rows = sheet.rows
    .map((row, r) => {
      const isHeader = sheet.header === true && r === 0;
      const cells = row
        .map((value, c) => {
          if (value === null || value === '') return '';
          const ref = `${columnName(c)}${r + 1}`;
          if (typeof value === 'number' && Number.isFinite(value))
            return `<c r="${ref}" s="${isHeader ? STYLE.header : STYLE.number}"><v>${value}</v></c>`;
          const text = String(value);
          let style: number = isHeader ? STYLE.header : STYLE.text;
          if (!isHeader && linkColumns.has(c) && /^https?:\/\//i.test(text)) {
            links.push(text);
            linkRefs.push(ref);
            style = STYLE.link;
          }
          return `<c r="${ref}" t="inlineStr" s="${style}"><is><t xml:space="preserve">${escapeXml(clip(text))}</t></is></c>`;
        })
        .join('');
      return `<row r="${r + 1}">${cells}</row>`;
    })
    .join('');

  const last = `${columnName(Math.max(cols, 1) - 1)}${Math.max(sheet.rows.length, 1)}`;
  const frozen =
    sheet.header && sheet.rows.length > 1
      ? `<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft"/>`
      : '';
  const widths = (sheet.widths ?? [])
    .map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`)
    .join('');
  const filter =
    sheet.header && sheet.rows.length > 0 ? `<autoFilter ref="A1:${escapeXml(last)}"/>` : '';
  const hyperlinks =
    linkRefs.length > 0
      ? `<hyperlinks>${linkRefs.map((ref, n) => `<hyperlink ref="${ref}" r:id="rId${n + 1}"/>`).join('')}</hyperlinks>`
      : '';

  const xml =
    `${XML_HEAD}<worksheet xmlns="${NS_MAIN}" xmlns:r="${NS_REL}">` +
    `<dimension ref="A1:${last}"/>` +
    `<sheetViews><sheetView workbookViewId="0"${selected ? ' tabSelected="1"' : ''}>${frozen}</sheetView></sheetViews>` +
    `<sheetFormatPr defaultRowHeight="15"/>` +
    (widths ? `<cols>${widths}</cols>` : '') +
    `<sheetData>${rows}</sheetData>` +
    filter +
    hyperlinks +
    `</worksheet>`;
  return { xml, links };
}

// ---------------------------------------------------------------- мелочи

function columnCount(sheet: XlsxSheet): number {
  return sheet.rows.reduce((max, row) => Math.max(max, row.length), 0);
}

/** 0 → A, 25 → Z, 26 → AA */
function columnName(index: number): string {
  let n = index + 1;
  let name = '';
  while (n > 0) {
    const rest = (n - 1) % 26;
    name = String.fromCharCode(65 + rest) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function uniqueSheetNames(names: string[]): string[] {
  const used = new Set<string>();
  return names.map((raw, i) => {
    const base =
      raw
        .replace(/[[\]:*?/\\]/g, ' ')
        .trim()
        .slice(0, 31) || `Лист${i + 1}`;
    let name = base;
    for (let n = 2; used.has(name.toLowerCase()); n += 1)
      name = `${base.slice(0, 31 - String(n).length - 1)} ${n}`;
    used.add(name.toLowerCase());
    return name;
  });
}

function clip(text: string): string {
  return text.length > MAX_CELL_TEXT ? `${text.slice(0, MAX_CELL_TEXT - 1)}…` : text;
}

/** Экранирование для XML; управляющие символы, которых XML не допускает, убираем. */
function escapeXml(text: string): string {
  return (
    text
      // eslint-disable-next-line no-control-regex -- именно управляющие символы и убираем
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]/g, '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  );
}

// ---------------------------------------------------------------- ZIP (без сжатия)

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) crc = (CRC_TABLE[(crc ^ byte) & 0xff] ?? 0) ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** Время и дата в формате MS-DOS — так их хранит ZIP */
function dosDateTime(date: Date): { time: number; day: number } {
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
    day: ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate(),
  };
}

function zipStore(files: { name: string; data: Uint8Array }[]): Uint8Array<ArrayBuffer> {
  const encoder = new TextEncoder();
  const { time, day } = dosDateTime(new Date());
  const entries = files.map((f) => ({ ...f, path: encoder.encode(f.name), crc: crc32(f.data) }));
  const localSize = entries.reduce((sum, e) => sum + 30 + e.path.length + e.data.length, 0);
  const centralSize = entries.reduce((sum, e) => sum + 46 + e.path.length, 0);
  const out = new Uint8Array(localSize + centralSize + 22);
  const view = new DataView(out.buffer);
  let at = 0;
  const u16 = (v: number) => {
    view.setUint16(at, v, true);
    at += 2;
  };
  const u32 = (v: number) => {
    view.setUint32(at, v, true);
    at += 4;
  };
  const bytes = (b: Uint8Array) => {
    out.set(b, at);
    at += b.length;
  };

  const offsets: number[] = [];
  for (const e of entries) {
    offsets.push(at);
    u32(0x04034b50);
    u16(20); // версия для распаковки
    u16(0x0800); // имена в UTF-8
    u16(0); // без сжатия
    u16(time);
    u16(day);
    u32(e.crc);
    u32(e.data.length);
    u32(e.data.length);
    u16(e.path.length);
    u16(0);
    bytes(e.path);
    bytes(e.data);
  }
  const centralAt = at;
  entries.forEach((e, i) => {
    u32(0x02014b50);
    u16(20);
    u16(20);
    u16(0x0800);
    u16(0);
    u16(time);
    u16(day);
    u32(e.crc);
    u32(e.data.length);
    u32(e.data.length);
    u16(e.path.length);
    u16(0); // extra
    u16(0); // комментарий
    u16(0); // диск
    u16(0); // внутренние атрибуты
    u32(0); // внешние атрибуты
    u32(offsets[i] ?? 0);
    bytes(e.path);
  });
  const centralLength = at - centralAt;
  u32(0x06054b50);
  u16(0);
  u16(0);
  u16(entries.length);
  u16(entries.length);
  u32(centralLength);
  u32(centralAt);
  u16(0);
  return out;
}
