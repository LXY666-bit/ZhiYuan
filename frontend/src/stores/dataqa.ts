import { defineStore } from 'pinia';
import { createIdempotencyKey } from '@/runs/runClient';
import {
  createDataQaAnalysis,
  createDataQaQuery,
  deleteDataQaQuery,
  getDataQaQuery,
  listDataQaQueries,
  type DataQaQuery,
} from '@/dataqa/dataqaClient';
import { getPublicError } from '@/utils/api';

const ACTIVE_STATUSES = new Set(['pending', 'running']);
const POLL_INTERVAL_MS = 1500;

const polling = new WeakMap<
  object,
  { timer: ReturnType<typeof setTimeout> | null; controller: AbortController | null }
>();

function pollState(store: object) {
  let state = polling.get(store);
  if (!state) {
    state = { timer: null, controller: null };
    polling.set(store, state);
  }
  return state;
}

export const useDataQaStore = defineStore('dataqa', {
  state: () => ({
    queries: [] as DataQaQuery[],
    selectedId: '' as string,
    questionDraft: '',
    analysisBusy: false,
    deletingId: '',
    loading: false,
    busy: false,
    error: '',
    scopeVersion: 0,
  }),
  getters: {
    selected(state): DataQaQuery | null {
      return state.queries.find((query) => query.id === state.selectedId) || null;
    },
    hasActive(state): boolean {
      return state.queries.some((query) => ACTIVE_STATUSES.has(query.status));
    },
  },
  actions: {
    stopPolling() {
      const state = pollState(this);
      if (state.timer) clearTimeout(state.timer);
      state.timer = null;
      state.controller?.abort();
      state.controller = null;
    },
    reset() {
      this.stopPolling();
      this.scopeVersion += 1;
      this.queries = [];
      this.selectedId = '';
      this.questionDraft = '';
      this.analysisBusy = false;
      this.deletingId = '';
      this.loading = false;
      this.busy = false;
      this.error = '';
    },
    async loadQueries() {
      const scope = this.scopeVersion;
      this.loading = true;
      this.error = '';
      try {
        const queries = await listDataQaQueries();
        if (scope !== this.scopeVersion) return;
        this.queries = queries;
        if (!this.selectedId && queries[0]) this.selectedId = queries[0].id;
        this.schedulePoll();
      } catch (error) {
        if (scope === this.scopeVersion) this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion) this.loading = false;
      }
    },
    async ask(question: string) {
      const trimmed = question.trim();
      if (!trimmed) return;
      this.busy = true;
      this.error = '';
      try {
        const query = await createDataQaQuery(trimmed, createIdempotencyKey());
        this.queries = [query, ...this.queries];
        this.selectedId = query.id;
        this.questionDraft = '';
        this.schedulePoll();
      } catch (error) {
        this.error = getPublicError(error).message;
        throw error;
      } finally {
        this.busy = false;
      }
    },
    async select(queryId: string) {
      this.selectedId = queryId;
      await this.refreshSelected();
    },
    async refreshSelected() {
      if (!this.selectedId) return;
      const query = await getDataQaQuery(this.selectedId);
      const index = this.queries.findIndex((item) => item.id === query.id);
      if (index >= 0) this.queries.splice(index, 1, query);
      else this.queries = [query, ...this.queries];
      this.schedulePoll();
    },
    async generateAnalysis() {
      const query = this.selected;
      if (!query || !query.result || query.result.analysis !== null) return;
      this.analysisBusy = true;
      this.error = '';
      try {
        const updated = await createDataQaAnalysis(query.id, createIdempotencyKey());
        const index = this.queries.findIndex((item) => item.id === updated.id);
        if (index >= 0) this.queries.splice(index, 1, updated);
      } catch (error) {
        this.error = getPublicError(error).message;
      } finally {
        this.analysisBusy = false;
      }
    },
    async deleteQuery(queryId: string) {
      const query = this.queries.find((item) => item.id === queryId);
      if (!query || ACTIVE_STATUSES.has(query.status)) return;
      const scope = this.scopeVersion;
      this.deletingId = queryId;
      this.error = '';
      try {
        await deleteDataQaQuery(queryId);
        if (scope !== this.scopeVersion) return;
        const index = this.queries.findIndex((item) => item.id === queryId);
        if (index >= 0) this.queries.splice(index, 1);
        if (this.selectedId === queryId) this.selectedId = this.queries[0]?.id ?? '';
      } catch (error) {
        if (scope === this.scopeVersion) this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion) this.deletingId = '';
      }
    },
    schedulePoll() {
      const state = pollState(this);
      if (!this.hasActive) {
        this.stopPolling();
        return;
      }
      if (state.timer) return;
      const tick = () => {
        state.timer = null;
        if (!this.hasActive) return;
        state.controller = new AbortController();
        void listDataQaQueries(state.controller.signal)
          .then((queries) => {
            this.queries = queries;
          })
          .catch(() => undefined)
          .finally(() => {
            if (this.hasActive) {
              state.timer = setTimeout(tick, POLL_INTERVAL_MS);
            } else {
              this.stopPolling();
            }
          });
      };
      state.timer = setTimeout(tick, POLL_INTERVAL_MS);
    },
  },
});
