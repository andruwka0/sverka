'use strict';

const tables = [
  {role: 'participants', title: 'Таблица 1. Участники', description: 'Участник конкретной процедуры', columns: ['participant_id', 'tender_id', 'company_name', 'inn', 'director_name', 'phone', 'email', 'address']},
  {role: 'officials', title: 'Таблица 2. Сотрудники', description: 'Сотрудник и его роль в процедуре', columns: ['official_id', 'full_name', 'position', 'role_in_tender', 'tender_id']},
  {role: 'related_persons', title: 'Таблица 3. Близкие лица', description: 'Близкое лицо сотрудника и родство', columns: ['official_id', 'relation_type', 'full_name', 'inn', 'phone', 'email', 'address']},
];
const levels = {high: ['hi', 'Высокий приоритет'], medium: ['md', 'Средний приоритет'], low: ['lo', 'Низкий приоритет']};
const ruleNames = {R1_PHONE_MATCH: 'Телефон', R2_ADDRESS_MATCH: 'Адрес', R3_NAME_FUZZY: 'ФИО'};
const inputs = new Map();
const form = document.querySelector('#check-form');
const compareButton = document.querySelector('#compare');
let busy = false;

// All file names and values from the API enter the page as text.
function element(tag, className = '', text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function step(name) {
  for (const node of document.querySelectorAll('[data-step]')) {
    node.classList.toggle('on', node.dataset.step === name);
    if (node.dataset.step === name) node.setAttribute('aria-current', 'step');
    else node.removeAttribute('aria-current');
  }
}

function clearErrors() {
  document.querySelector('#errors').hidden = true;
  for (const {card, chips} of inputs.values()) {
    card.classList.remove('bad');
    for (const chip of chips.values()) chip.classList.remove('x');
  }
}

function showErrors(errors) {
  const panel = document.querySelector('#errors');
  panel.replaceChildren(element('h2', '', 'Проверьте файлы'));
  const list = element('ul');
  for (const error of errors) {
    const table = tables.find(item => item.role === error.file_role);
    const location = [table?.title, error.field, error.rows ? `строки ${error.rows.join(', ')}` : ''].filter(Boolean).join(' · ');
    list.append(element('li', '', `${location ? location + ' — ' : ''}${error.message}`));
    const input = inputs.get(error.file_role);
    if (input) {
      input.card.classList.add('bad');
      input.chips.get(error.field)?.classList.add('x');
    }
  }
  panel.append(list);
  panel.hidden = false;
}

function updateSelection() {
  const chosen = [...inputs.values()].filter(({input}) => input.files.length).length;
  compareButton.disabled = busy || chosen !== 3;
  compareButton.textContent = busy ? 'Сравниваем…' : 'Сравнить';
  document.querySelector('#file-status').textContent = busy ? 'Читаем файлы и проверяем совпадения' : `Выбрано файлов ${chosen} из 3`;
  for (const {input} of inputs.values()) input.disabled = busy;
  form.setAttribute('aria-busy', String(busy));
}

for (const table of tables) {
  const card = element('section', 'c');
  const title = element('h3', '', table.title);
  title.id = `${table.role}-title`;
  card.setAttribute('aria-labelledby', title.id);
  const input = element('input');
  input.type = 'file';
  input.id = table.role;
  input.name = table.role;
  input.accept = '.xlsx';
  input.setAttribute('aria-label', `Загрузить файл — ${table.title}`);
  const status = element('p', 'file-state', 'Файл не выбран');
  status.id = `${table.role}-state`;
  input.setAttribute('aria-describedby', status.id);
  const columns = element('div');
  const chips = new Map();
  for (const column of table.columns) {
    const chip = element('span', 'f', column);
    chips.set(column, chip);
    columns.append(chip);
  }
  card.append(title, element('p', '', table.description), input, status, columns);
  document.querySelector('#uploads').append(card);
  inputs.set(table.role, {input, card, chips});
  input.addEventListener('change', () => {
    clearErrors();
    status.textContent = input.files[0]?.name || 'Файл не выбран';
    updateSelection();
  });
}

function renderMatch(match) {
  const evidence = element('div', 'ev');
  const body = element('div');
  body.append(element('b', '', ruleNames[match.rule_id] || match.rule_id));
  const values = element('dl', 'evidence-values');
  values.append(element('dt', '', match.left_field === 'participants.director_name' ? 'Директор участника' : 'Участник'), element('dd', '', match.left_raw), element('dt', '', 'Близкое лицо'), element('dd', '', match.right_raw));
  body.append(values);
  if (match.similarity !== null && match.similarity !== undefined) body.append(element('p', 'muted', `Сходство ${(match.similarity * 100).toFixed(1)} %`));
  body.append(element('p', 'muted', `После обработки — ${match.left_normalized} / ${match.right_normalized}`));
  evidence.append(element('i', '', `+${match.points}`), body);
  return evidence;
}

function renderAlert(alert) {
  const [className, label] = levels[alert.level];
  const card = element('article', `cd ${className}`);
  const score = element('div', 'sc');
  score.append(element('b', '', String(alert.score)), element('span', '', 'баллов'), element('br'), element('em', '', label));
  const body = element('div', 'bd');
  body.append(element('span', 'muted', `Процедура ${alert.tender_id}`));
  const people = element('div');
  people.append(element('b', '', 'Участник '), document.createTextNode(alert.participant.company_name + ' '), element('span', 'f', alert.participant.participant_id), element('br'), element('b', '', 'Близкое лицо '), document.createTextNode(`${alert.related_person.full_name} · ${alert.related_person.relation_type}`), element('br'), element('b', '', 'Сотрудник '), document.createTextNode(`${alert.official.full_name} · ${alert.official.position} · ${alert.official.role_in_tender} `), element('span', 'f', alert.official.official_id));
  body.append(people);
  for (const match of alert.matches) body.append(renderMatch(match));
  const sources = element('div', 'wh');
  for (const source of alert.sources) {
    const table = tables.find(item => item.role === source.file_role);
    const location = element('div');
    location.append(element('small', '', table?.title || source.file_role), element('br'), element('b', '', source.filename), element('br'), document.createTextNode(`${source.sheet ? source.sheet + ', ' : ''}строка ${source.row}`));
    sources.append(location);
  }
  body.append(sources);
  const decisions = element('div', 'dc');
  decisions.append(element('strong', '', 'Решение проверяющего'));
  for (const text of ['Передать на ручную проверку', 'Проверка не нужна']) {
    const button = element('button', 'ob', text);
    button.type = 'button';
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => {
      const wasPressed = button.getAttribute('aria-pressed') === 'true';
      for (const other of decisions.querySelectorAll('button')) other.setAttribute('aria-pressed', 'false');
      button.setAttribute('aria-pressed', String(!wasPressed));
      step('review');
    });
    decisions.append(button);
  }
  body.append(decisions);
  card.append(score, body);
  return card;
}

function renderResult(data) {
  const summary = document.querySelector('#summary');
  summary.replaceChildren();
  const read = tables.map(t => data.summary.rows_read[t.role]);
  const skipped = Object.values(data.summary.rows_skipped).reduce((sum, count) => sum + count, 0);
  for (const [value, label] of [[data.summary.alert_count, 'карточек найдено'], [read.join(' · '), 'строк прочитано в таблицах 1 · 2 · 3'], [skipped, 'строк пропущено']]) {
    const block = element('div', 'c');
    block.append(element('b', 'sm', String(value)), element('p', '', label));
    summary.append(block);
  }
  document.querySelector('#alerts').replaceChildren(...data.alerts.map(renderAlert));
  document.querySelector('#empty').hidden = data.alerts.length !== 0;
  document.querySelector('#decision-note').hidden = data.alerts.length === 0;
  const warnings = document.querySelector('#warning-list');
  warnings.replaceChildren();
  for (const warning of data.warnings) {
    const table = tables.find(t => t.role === warning.file_role);
    warnings.append(element('li', '', `${table?.title || warning.file_role}${warning.row ? ', строка ' + warning.row : ''}${warning.field ? ', ' + warning.field : ''} — ${warning.message}`));
  }
  document.querySelector('#warnings').hidden = data.warnings.length === 0;
  document.querySelector('#upload-screen').hidden = true;
  document.querySelector('#result-screen').hidden = false;
  step('result');
  document.querySelector('#result-title').focus();
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  clearErrors();
  const body = new FormData();
  for (const [role, {input}] of inputs) {
    if (!input.files[0]) return;
    if (!input.files[0].name.toLowerCase().endsWith('.xlsx')) {
      showErrors([{file_role: role, message: 'Выберите книгу в формате .xlsx'}]);
      return;
    }
    body.append(role, input.files[0]);
  }
  busy = true;
  step('processing');
  updateSelection();
  try {
    const response = await fetch('/api/v1/checks', {method: 'POST', body});
    if (response.status === 422) {
      const data = await response.json();
      showErrors(data.errors);
      step('input');
    } else if (!response.ok) {
      throw new Error('server');
    } else {
      renderResult(await response.json());
    }
  } catch {
    showErrors([{message: 'Не удалось выполнить сверку. Проверьте, запущен ли сервер, и повторите попытку.'}]);
    step('input');
  } finally {
    busy = false;
    updateSelection();
  }
});

document.querySelector('#back').addEventListener('click', () => {
  document.querySelector('#result-screen').hidden = true;
  document.querySelector('#upload-screen').hidden = false;
  document.querySelector('#alerts').replaceChildren();
  clearErrors();
  step('input');
  document.querySelector('#participants').focus();
});
