import { defineStore } from 'pinia';
import {
  getDataQaSemanticSchema,
  saveDataQaSemanticMetadata,
  type DataQaSemanticMetadataInput,
  type DataQaSemanticSchema,
} from '@/dataqa/dataqaClient';
import { getPublicError } from '@/utils/api';

export const useDataQaSchemaStore = defineStore('dataqa-schema', {
  state: () => ({
    schema: null as DataQaSemanticSchema | null,
    loading: false,
    saving: false,
    error: '',
    scopeVersion: 0,
  }),
  actions: {
    reset() {
      this.scopeVersion += 1;
      this.schema = null;
      this.loading = false;
      this.saving = false;
      this.error = '';
    },
    async load() {
      const scope = this.scopeVersion;
      this.loading = true;
      this.error = '';
      try {
        const schema = await getDataQaSemanticSchema();
        if (scope === this.scopeVersion) this.schema = schema;
      } catch (error) {
        if (scope === this.scopeVersion) this.error = getPublicError(error).message;
      } finally {
        if (scope === this.scopeVersion) this.loading = false;
      }
    },
    async save(input: DataQaSemanticMetadataInput) {
      this.saving = true;
      this.error = '';
      try {
        this.schema = await saveDataQaSemanticMetadata(input);
      } catch (error) {
        this.error = getPublicError(error).message;
        throw error;
      } finally {
        this.saving = false;
      }
    },
  },
});
