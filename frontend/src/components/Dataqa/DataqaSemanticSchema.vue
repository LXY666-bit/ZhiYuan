<template>
  <section class="semantic-schema-page">
    <header class="semantic-header">
      <div>
        <p class="semantic-kicker">DATA QA ADMIN</p>
        <h1>数据字典</h1>
        <p>维护业务说明和别名，让智能问数在生成 SQL 前准确筛选表与字段。</p>
      </div>
      <button
        type="button"
        class="semantic-secondary"
        :disabled="store.loading"
        @click="store.load"
      >
        <i class="fa-solid fa-rotate-right" :class="{ 'fa-spin': store.loading }"></i>
        刷新目录
      </button>
    </header>

    <p v-if="store.error" class="semantic-error" role="alert">{{ store.error }}</p>
    <p v-if="store.loading" class="semantic-loading" role="status">
      正在读取 SQL Assistant 已授权目录…
    </p>

    <div v-else-if="store.schema" class="semantic-layout">
      <aside class="semantic-card semantic-list" aria-label="数据表">
        <button
          v-for="table in store.schema.tables"
          :key="tableKey(table)"
          type="button"
          :class="[
            'semantic-table',
            { active: selectedTableKey === tableKey(table) && !selectedColumnName },
          ]"
          @click="selectTable(table)"
        >
          <strong>{{ table.schema_name }}.{{ table.table_name }}</strong>
          <small>{{ table.description || '尚未填写业务说明' }}</small>
        </button>
      </aside>

      <main v-if="selectedTable" class="semantic-card semantic-detail">
        <div class="semantic-title-row">
          <div>
            <p class="semantic-object-type">{{ selectedColumn ? '字段' : '数据表' }}</p>
            <h2>
              {{ selectedTable.schema_name }}.{{ selectedTable.table_name
              }}<template v-if="selectedColumn">.{{ selectedColumn.column_name }}</template>
            </h2>
            <p v-if="selectedColumn" class="semantic-type">{{ selectedColumn.data_type }}</p>
          </div>
          <span v-if="selectedColumn?.sensitive" class="semantic-sensitive"
            >敏感字段：不会发送给模型</span
          >
        </div>

        <label>
          业务说明
          <textarea
            v-model="draftDescription"
            rows="3"
            maxlength="1000"
            placeholder="例如：订单实际支付金额"
          ></textarea>
        </label>
        <label>
          别名（用中文逗号或英文逗号分隔）
          <input
            v-model="draftAliases"
            maxlength="1000"
            placeholder="例如：销售额、成交金额、支付金额"
          />
        </label>
        <button type="button" class="semantic-primary" :disabled="store.saving" @click="save">
          {{ store.saving ? '保存中…' : '保存当前说明' }}
        </button>

        <section class="semantic-columns">
          <h3>字段</h3>
          <button
            v-for="column in selectedTable.columns"
            :key="column.column_name"
            type="button"
            :class="['semantic-column', { active: selectedColumnName === column.column_name }]"
            @click="selectColumn(column.column_name)"
          >
            <span>
              <strong>{{ column.column_name }}</strong>
              <small>{{ column.description || '尚未填写业务说明' }}</small>
            </span>
            <em>{{ column.sensitive ? '敏感' : column.data_type }}</em>
          </button>
        </section>
      </main>
    </div>
    <p v-else class="semantic-loading">当前没有可维护的授权数据表。</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import type { DataQaSemanticTable } from '@/dataqa/dataqaClient';
import { useDataQaSchemaStore } from '@/stores/dataqaSchema';

const store = useDataQaSchemaStore();
const selectedTableKey = ref('');
const selectedColumnName = ref('');
const draftDescription = ref('');
const draftAliases = ref('');

const tableKey = (table: DataQaSemanticTable) => `${table.schema_name}.${table.table_name}`;
const selectedTable = computed(
  () => store.schema?.tables.find((table) => tableKey(table) === selectedTableKey.value) || null
);
const selectedColumn = computed(
  () =>
    selectedTable.value?.columns.find(
      (column) => column.column_name === selectedColumnName.value
    ) || null
);

function setDraft(description: string, aliases: string[]) {
  draftDescription.value = description;
  draftAliases.value = aliases.join('、');
}

function selectTable(table: DataQaSemanticTable) {
  selectedTableKey.value = tableKey(table);
  selectedColumnName.value = '';
  setDraft(table.description, table.aliases);
}

function selectColumn(columnName: string) {
  if (!selectedTable.value) return;
  const column = selectedTable.value.columns.find((item) => item.column_name === columnName);
  if (!column) return;
  selectedColumnName.value = columnName;
  setDraft(column.description, column.aliases);
}

async function save() {
  if (!selectedTable.value) return;
  const aliases = draftAliases.value
    .split(/[，,、]/)
    .map((value) => value.trim())
    .filter(Boolean);
  await store.save({
    schema_name: selectedTable.value.schema_name,
    table_name: selectedTable.value.table_name,
    column_name: selectedColumnName.value,
    description: draftDescription.value,
    aliases,
  });
  const refreshed = selectedTable.value;
  if (refreshed) {
    const column = refreshed.columns.find((item) => item.column_name === selectedColumnName.value);
    setDraft(
      column ? column.description : refreshed.description,
      column ? column.aliases : refreshed.aliases
    );
  }
}

onMounted(async () => {
  await store.load();
  if (store.schema?.tables[0]) selectTable(store.schema.tables[0]);
});
</script>

<style scoped lang="scss">
.semantic-schema-page {
  width: 100%;
  height: 100%;
  min-height: 0;
  padding: 25px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.semantic-header,
.semantic-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}
.semantic-header {
  padding-bottom: 21px;
  border-bottom: 1px solid var(--line);
}
.semantic-header h1 {
  margin-top: 5px;
  font-size: 26px;
  letter-spacing: -0.045em;
}
.semantic-detail h2 {
  margin: 3px 0 0;
  font-size: var(--font-title-sm);
  letter-spacing: -0.02em;
}
.semantic-header p:not(.semantic-kicker) {
  color: var(--muted);
  margin: 0;
  font-size: var(--font-caption);
}
.semantic-kicker,
.semantic-object-type {
  color: var(--mint);
  font-size: var(--font-micro);
  letter-spacing: 0.12em;
  margin: 0;
}
.semantic-layout {
  display: grid;
  grid-template-columns: minmax(220px, 0.7fr) minmax(0, 2fr);
  gap: 10px;
  margin-top: 18px;
}
.semantic-card {
  border: 1px solid var(--line);
  border-radius: 15px;
  background: var(--surface);
  padding: 14px;
}
.semantic-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-self: start;
}
.semantic-table,
.semantic-column {
  border: 1px solid transparent;
  background: transparent;
  color: inherit;
  text-align: left;
  border-radius: 9px;
  padding: 9px;
  cursor: pointer;
}
.semantic-table strong,
.semantic-column strong {
  font-size: var(--font-caption);
}
.semantic-table small,
.semantic-column small {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: var(--font-micro);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.semantic-table.active,
.semantic-column.active {
  border-color: var(--mint);
  background: color-mix(in srgb, var(--mint) 10%, transparent);
}
.semantic-detail label {
  display: grid;
  gap: 6px;
  margin-top: 14px;
  font-weight: 600;
  font-size: var(--font-caption);
}
.semantic-detail textarea,
.semantic-detail input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-soft);
  color: inherit;
  padding: 8px 9px;
  font: inherit;
  font-size: var(--font-caption);
  line-height: 1.45;
}
.semantic-detail textarea::placeholder,
.semantic-detail input::placeholder {
  color: var(--muted-strong);
}
.semantic-primary,
.semantic-secondary {
  border: 0;
  border-radius: 8px;
  min-height: 38px;
  padding: 0 13px;
  cursor: pointer;
  color: var(--mint-ink);
  background: var(--mint);
  margin-top: 16px;
  font-size: var(--font-caption);
}
.semantic-secondary {
  margin-top: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text-soft);
}
.semantic-primary:disabled,
.semantic-secondary:disabled {
  opacity: 0.6;
  cursor: wait;
}
.semantic-columns {
  border-top: 1px solid var(--line);
  margin-top: 20px;
  padding-top: 14px;
}
.semantic-columns h3 {
  margin: 0 0 8px;
  font-size: var(--font-body);
}
.semantic-column {
  display: flex;
  width: 100%;
  justify-content: space-between;
  align-items: center;
}
.semantic-column em,
.semantic-sensitive {
  color: var(--muted);
  font-size: var(--font-micro);
  font-style: normal;
}
.semantic-type {
  margin-top: 3px;
  color: var(--muted);
  font-size: var(--font-micro);
}
.semantic-sensitive {
  color: #d97706;
}
.semantic-error {
  color: #dc2626;
  margin-top: 18px;
  font-size: var(--font-caption);
}
.semantic-loading {
  color: var(--muted);
  margin-top: 24px;
  font-size: var(--font-caption);
}
@media (max-width: 760px) {
  .semantic-schema-page {
    padding: 17px 13px;
  }
  .semantic-layout {
    grid-template-columns: 1fr;
  }
  .semantic-header {
    flex-direction: column;
  }
}
</style>
