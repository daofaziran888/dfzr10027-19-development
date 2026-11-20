<template>
  <section class="page" data-module="cross_source_daily">
    <header class="page-head">
      <div>
        <h2>跨源日报包</h2>
        <p class="page-desc">按业务截止日合并预测、分群、实验三章的已完成产物；每章保留实际业务日与来源版本，仅统计周期可比的指标形成同日对照。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-generate" type="button" @click="openGenerate">生成跨源日报包</button>
        <button class="btn" type="button" @click="reload">刷新版本</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">报表包版本数</span>
        <strong class="stat-value">{{ packages.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">含迟到章节的版本</span>
        <strong class="stat-value">{{ latePackageCount }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">最新版本</span>
        <strong class="stat-value">{{ latestVersion ?? '—' }}</strong>
      </article>
    </div>

    <table class="data-table" data-testid="package-table">
      <thead>
        <tr>
          <th>报表包编号</th>
          <th>版本</th>
          <th>业务截止日</th>
          <th>关联报表</th>
          <th>章节日期（预测 / 分群 / 实验）</th>
          <th>迟到章节</th>
          <th>可同日对照指标</th>
          <th>编制时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="pkg in packages" :key="String(pkg.id)" :data-testid="`package-row-${pkg.id}`">
          <td>{{ pkg['报表包编号'] }}</td>
          <td>{{ pkg['版本'] }}</td>
          <td>{{ pkg['业务截止日'] }}</td>
          <td>{{ pkg['关联报表编号'] ?? '未关联' }}</td>
          <td>
            <span v-for="chapter in pkg['章节']" :key="chapter['章节']" class="chapter-date">
              {{ chapter['章节'] }} {{ chapter['实际业务日'] }}
              <em v-if="chapter['统计迟到']" class="late-tag">迟到</em>
            </span>
          </td>
          <td>{{ pkg['摘要']['迟到章节'].length ? pkg['摘要']['迟到章节'].join('、') : '—' }}</td>
          <td>{{ pkg['摘要']['可同日对照指标'].join('、') || '—' }}</td>
          <td>{{ pkg['编制时间'] }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`open-detail-${pkg.id}`" @click="openDetail(pkg.id)">
              查看对照
            </button>
          </td>
        </tr>
        <tr v-if="!packages.length">
          <td colspan="9" class="empty-state">暂无跨源日报包，先按业务截止日生成一版</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showGenerate" class="modal-backdrop" data-testid="generate-modal">
      <form class="modal" @submit.prevent="submitGenerate">
        <h3>生成跨源日报包</h3>
        <label class="create-field">
          <span>业务截止日（必填）</span>
          <input v-model="form.business_cutoff" data-testid="gen-cutoff" type="date" required />
        </label>
        <label class="create-field">
          <span>关联分析报表 ID（可选，填入 report_gen 记录 id）</span>
          <input v-model="form.report_entry_id" data-testid="gen-report-id" placeholder="例如 1" />
        </label>
        <label class="create-field">
          <span>实验统计快照截止日（可选；实验迟到时填前一日，留空取最新已完成快照）</span>
          <input v-model="form.experiment_max_cutoff" data-testid="gen-exp-cutoff" type="date" />
        </label>
        <p class="page-desc">预测与分群始终选取不晚于业务截止日的最新已完成产物；实验章节在快照迟到时回退到最近完成日并标记迟到。</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="showGenerate = false">取消</button>
          <button class="btn primary" data-testid="submit-generate" type="submit" :disabled="submitting">
            {{ submitting ? '出包中…' : '确认出包' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="detail" class="modal-backdrop" data-testid="detail-modal" @click.self="detail = null">
      <div class="modal modal-wide">
        <header class="page-head">
          <div>
            <h3>{{ detail['报表包编号'] }} · {{ detail['版本'] }}</h3>
            <p class="page-desc">
              业务截止日 {{ detail['业务截止日'] }} ｜ 关联报表 {{ detail['关联报表编号'] ?? '未关联' }}
              ｜ 编制时间 {{ detail['编制时间'] }}
            </p>
          </div>
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </header>

        <h4>章节数据版本（每章一份完整产物）</h4>
        <table class="data-table" data-testid="chapter-table">
          <thead>
            <tr>
              <th>章节</th><th>来源模块</th><th>产物编号</th><th>来源版本</th>
              <th>业务截止日</th><th>实际业务日</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="chapter in detail['章节']" :key="chapter['章节']">
              <td>{{ chapter['章节'] }}</td>
              <td>{{ chapter['来源模块'] }}</td>
              <td>{{ chapter['产物编号'] }}</td>
              <td>{{ chapter['来源版本'] }}</td>
              <td>{{ chapter['业务截止日'] }}</td>
              <td>
                {{ chapter['实际业务日'] }}
                <em v-if="chapter['统计迟到']" class="late-tag">统计迟到</em>
              </td>
              <td>{{ chapter['产物']['状态'] }}</td>
            </tr>
          </tbody>
        </table>

        <template v-for="chapter in detail['章节']" :key="`lift-${chapter['章节']}`">
          <template v-if="chapter['章节'] === '实验'">
            <h4>实验转化变化（来自数据集市已完成统计快照）</h4>
            <table class="data-table" data-testid="lift-table">
              <thead>
                <tr>
                  <th>实验编号</th><th>对照组转化率</th><th>实验组转化率</th>
                  <th>绝对变化</th><th>相对变化</th><th>z 值</th><th>显著(0.05)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="lift in chapter['实验转化变化']" :key="lift['实验编号']">
                  <td>{{ lift['实验编号'] }}</td>
                  <td>{{ formatValue(lift['对照组转化率']) }}</td>
                  <td>{{ formatValue(lift['实验组转化率']) }}</td>
                  <td>{{ formatValue(lift['绝对变化']) }}</td>
                  <td>{{ lift['相对变化'] === null ? '—' : formatValue(lift['相对变化']) }}</td>
                  <td>{{ formatValue(lift['z_score']) }}</td>
                  <td>{{ lift['显著(0.05)'] ? '显著' : '不显著' }}</td>
                </tr>
              </tbody>
            </table>
          </template>
        </template>

        <h4>同日对照值（仅统计周期一致且各章同日有值，可直接比较）</h4>
        <table class="data-table" data-testid="comparison-table">
          <thead>
            <tr>
              <th>日期</th><th>指标编号</th><th>指标名称</th><th>统计周期</th>
              <th>对照章节</th><th>章节值</th><th>单位</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in detail['同日对照']['comparable']" :key="`${row['日期']}-${row['指标编号']}`">
              <td>{{ row['日期'] }}</td>
              <td>{{ row['指标编号'] }}</td>
              <td>{{ row['指标名称'] }}</td>
              <td>{{ row['统计周期'] }}</td>
              <td>{{ row['对照章节'].join('、') }}</td>
              <td>
                <span v-for="(label, chapter) in row['章节值']" :key="label" class="compare-value">
                  {{ label }} {{ formatValue(chapter) }}
                </span>
              </td>
              <td>{{ row['单位'] }}</td>
            </tr>
            <tr v-if="!detail['同日对照']['comparable'].length">
              <td colspan="7" class="empty-state">当前版本没有可同日直接比较的指标</td>
            </tr>
          </tbody>
        </table>

        <h4>不可同日对照项（含原因，避免误读）</h4>
        <table class="data-table" data-testid="non-comparison-table">
          <thead>
            <tr><th>日期</th><th>指标编号</th><th>出现章节</th><th>统计周期</th><th>原因</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in detail['同日对照']['non_comparable']" :key="`n-${row['日期']}-${row['指标编号']}`">
              <td>{{ row['日期'] }}</td>
              <td>{{ row['指标编号'] }}</td>
              <td>{{ row['出现章节'].join('、') }}</td>
              <td>{{ row['统计周期'] }}</td>
              <td>{{ row['不可比较原因'] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ packages.length }} 个跨源日报包版本</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Lift = {
  '实验编号': string
  '对照组转化率': number
  '实验组转化率': number
  '绝对变化': number
  '相对变化': number | null
  'z_score': number
  '显著(0.05)': boolean
}

type Chapter = {
  '章节': string
  '来源模块': string
  '产物编号': string
  '来源版本': string
  '业务截止日': string
  '实际业务日': string
  '统计迟到': boolean
  '产物': { '状态': string }
  '实验转化变化'?: Lift[]
}

type ComparisonRow = {
  '日期': string
  '指标编号': string
  '指标名称': string
  '统计周期': string
  '单位': string
  '对照章节': string[]
  '章节值': Record<string, number>
}

type NonComparisonRow = {
  '日期': string
  '指标编号': string
  '出现章节': string[]
  '统计周期': string
  '不可比较原因': string
}

type Package = {
  id: number
  '报表包编号': string
  '版本': string
  '业务截止日': string
  '编制时间': string
  '关联报表编号': string | null
  '章节': Chapter[]
  '摘要': {
    '迟到章节': string[]
    '可同日对照指标': string[]
    '可对照记录数': number
    '不可对照记录数': number
  }
  '同日对照': {
    comparable: ComparisonRow[]
    non_comparable: NonComparisonRow[]
  }
}

const packages = ref<Package[]>([])
const detail = ref<Package | null>(null)
const showGenerate = ref(false)
const submitting = ref(false)
const errorMessage = ref('')
const form = ref({ business_cutoff: '2026-08-30', report_entry_id: '1', experiment_max_cutoff: '' })

const latePackageCount = computed(
  () => packages.value.filter((pkg) => pkg['摘要']['迟到章节'].length > 0).length,
)
const latestVersion = computed(() => packages.value[packages.value.length - 1]?.['版本'])

function formatValue(value: number | string | null): string {
  if (value === null || value === undefined) return '—'
  return typeof value === 'number' ? String(value) : value
}

function openGenerate() {
  form.value = { business_cutoff: '2026-08-30', report_entry_id: '1', experiment_max_cutoff: '' }
  errorMessage.value = ''
  showGenerate.value = true
}

async function submitGenerate() {
  submitting.value = true
  errorMessage.value = ''
  const payload: Record<string, string | number> = { business_cutoff: form.value.business_cutoff }
  if (form.value.report_entry_id.trim()) {
    payload.report_entry_id = Number(form.value.report_entry_id.trim())
  }
  if (form.value.experiment_max_cutoff) {
    payload.experiment_max_cutoff = form.value.experiment_max_cutoff
  }
  try {
    const response = await request('/api/cross_source_daily/packages', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) throw new Error(result.message || '出包失败')
    showGenerate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '出包失败'
  } finally {
    submitting.value = false
  }
}

async function openDetail(packageId: number) {
  errorMessage.value = ''
  try {
    detail.value = await fetchJson<Package>(`/api/cross_source_daily/packages/${packageId}`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报表包详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<{ items: Package[] }>('/api/cross_source_daily/packages')
    packages.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '跨源日报版本读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.modal-wide { width: min(1080px, 96vw); }
.chapter-date { display: inline-block; margin-right: 10px; white-space: nowrap; }
.late-tag {
  font-style: normal;
  font-size: 11px;
  color: #b45309;
  background: #fef3c7;
  border-radius: 4px;
  padding: 1px 5px;
  margin-left: 4px;
}
.compare-value { display: inline-block; margin-right: 12px; white-space: nowrap; }
h4 { margin: 18px 0 8px; }
</style>
