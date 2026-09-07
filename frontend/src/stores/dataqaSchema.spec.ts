import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getDataQaSemanticSchema,
  saveDataQaSemanticMetadata,
  type DataQaSemanticSchema,
} from '@/dataqa/dataqaClient';
import { useDataQaSchemaStore } from './dataqaSchema';

vi.mock('@/dataqa/dataqaClient', () => ({
  getDataQaSemanticSchema: vi.fn(),
  saveDataQaSemanticMetadata: vi.fn(),
}));

const schema: DataQaSemanticSchema = {
  fingerprint: 'a'.repeat(64),
  tables: [
    {
      schema_name: 'public',
      table_name: 'orders',
      description: '支付订单事实表',
      aliases: ['销售订单'],
      columns: [],
    },
  ],
};

describe('dataqa semantic schema store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('loads the admin data dictionary into a single store-owned state', async () => {
    vi.mocked(getDataQaSemanticSchema).mockResolvedValue(schema);
    const store = useDataQaSchemaStore();

    await store.load();

    expect(store.schema).toEqual(schema);
    expect(store.error).toBe('');
  });

  it('saves normalized editor input through the canonical metadata endpoint', async () => {
    vi.mocked(saveDataQaSemanticMetadata).mockResolvedValue(schema);
    const store = useDataQaSchemaStore();
    const input = {
      schema_name: 'public',
      table_name: 'orders',
      column_name: 'pay_amt',
      description: '订单实际支付金额',
      aliases: ['销售额'],
    };

    await store.save(input);

    expect(saveDataQaSemanticMetadata).toHaveBeenCalledWith(input);
    expect(store.schema).toEqual(schema);
  });
});
