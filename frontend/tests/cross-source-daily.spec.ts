import { expect, test } from '@playwright/test'

/**
 * 跨源日报包验收：
 * 1. 预测/分群到 8/30、实验迟到（快照截止 8/29）生成第一版；
 * 2. 补齐实验后再次生成第二版；
 * 3. 经报表入口分别打开新旧两版，核对章节日期、来源版本与同日对照值。
 * 包 id 按生成前的版本数动态推导，保证重复执行不受历史数据影响。
 */
test('跨源日报：迟到出包、补齐再出包、新旧版本对照核对', async ({ page, request }) => {
  const browserErrors: string[] = []
  page.on('pageerror', (e) => browserErrors.push(e.message))
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) browserErrors.push(`${r.status()} ${r.url()}`)
  })

  const initial = await request.get('/api/cross_source_daily/packages')
  const initialBody = await initial.json()
  const firstId = initialBody.total + 1
  const secondId = firstId + 1

  // 报表生成入口提供跳转
  await page.goto('/report_gen')
  await page.getByTestId('goto-cross-source').click()
  await expect(page).toHaveURL(/\/cross_source_daily$/)
  await expect(page.getByRole('heading', { name: '跨源日报包' })).toBeVisible()

  // ---- 第一版：实验迟到 ----
  await page.getByTestId('open-generate').click()
  await expect(page.getByTestId('generate-modal')).toBeVisible()
  await page.getByTestId('gen-cutoff').fill('2026-08-30')
  await page.getByTestId('gen-report-id').fill('1')
  await page.getByTestId('gen-exp-cutoff').fill('2026-08-29')
  await page.getByTestId('submit-generate').click()
  await expect(page.getByTestId('generate-modal')).toHaveCount(0)

  const row1 = page.getByTestId(`package-row-${firstId}`)
  await expect(row1).toBeVisible()
  await expect(row1).toContainText(`v${firstId}`)
  await expect(row1).toContainText('预测 2026-08-30')
  await expect(row1).toContainText('分群 2026-08-30')
  await expect(row1).toContainText('实验 2026-08-29')
  await expect(row1).toContainText('迟到')

  // 打开第一版详情核对
  await page.getByTestId(`open-detail-${firstId}`).click()
  const modal = page.getByTestId('detail-modal')
  await expect(modal).toBeVisible()
  const chapterTable = page.getByTestId('chapter-table')
  await expect(chapterTable).toContainText('FORE-PKG-20260830')
  await expect(chapterTable).toContainText('COHO-PKG-20260830')
  await expect(chapterTable).toContainText('MART-SNAP-20260829')
  const oldExperimentRow = chapterTable.locator('tbody tr', { hasText: '实验' })
  await expect(oldExperimentRow).toContainText('2026-08-29')
  await expect(oldExperimentRow).toContainText('统计迟到')

  // 实验转化变化由快照计数计算
  const liftTable = page.getByTestId('lift-table')
  await expect(liftTable).toContainText('EXPE-001')
  await expect(liftTable).toContainText('0.07')
  await expect(liftTable).toContainText('0.0824')

  // 第一版同日对照只到 8/29，且只有统计周期一致的日粒度指标
  const comparisonTable = page.getByTestId('comparison-table')
  const firstVersionDates = await comparisonTable.locator('tbody tr td:first-child').allInnerTexts()
  expect(firstVersionDates.length).toBeGreaterThan(0)
  expect(firstVersionDates.every((d) => d <= '2026-08-29')).toBeTruthy()
  await expect(comparisonTable).toContainText('METR-CVR')
  await expect(comparisonTable).toContainText('METR-GMV')
  // 周粒度分群规模不可同日对照，且带周期/缺失原因
  const nonComparison = page.getByTestId('non-comparison-table')
  await expect(nonComparison).toContainText('METR-COHORT-SCALE')
  await expect(nonComparison).toContainText('周')
  await expect(nonComparison).toContainText('无法形成跨章节同日对照')
  await modal.getByRole('button', { name: '关闭' }).click()
  await expect(modal).toHaveCount(0)

  // ---- 第二版：补齐实验 ----
  await page.getByTestId('open-generate').click()
  await page.getByTestId('gen-cutoff').fill('2026-08-30')
  await page.getByTestId('gen-report-id').fill('1')
  await page.getByTestId('gen-exp-cutoff').fill('')
  await page.getByTestId('submit-generate').click()
  await expect(page.getByTestId('generate-modal')).toHaveCount(0)

  const row2 = page.getByTestId(`package-row-${secondId}`)
  await expect(row2).toBeVisible()
  await expect(row2).toContainText('实验 2026-08-30')
  await expect(row2).not.toContainText('迟到')

  // 打开第二版，核对 8/30 同日对照值与新版本
  await page.getByTestId(`open-detail-${secondId}`).click()
  const modal2 = page.getByTestId('detail-modal')
  await expect(page.getByTestId('chapter-table')).toContainText('MART-SNAP-20260830')
  const newExperimentRow = page.getByTestId('chapter-table').locator('tbody tr', { hasText: '实验' })
  await expect(newExperimentRow).toContainText('2026-08-30')
  const cutoffRows = page.getByTestId('comparison-table').locator('tbody tr', { hasText: '2026-08-30' })
  await expect(cutoffRows.first()).toBeVisible()
  const cutoffMetrics = await cutoffRows.locator('td:nth-child(2)').allInnerTexts()
  expect(cutoffMetrics).toContain('METR-CVR')
  expect(cutoffMetrics).toContain('METR-GMV')

  // 回到列表，两版共存，可再次打开旧版核对
  await modal2.getByRole('button', { name: '关闭' }).click()
  await expect(page.getByTestId(`package-row-${firstId}`)).toBeVisible()
  await expect(page.getByTestId(`package-row-${secondId}`)).toBeVisible()
  await page.getByTestId(`open-detail-${firstId}`).click()
  const reopenedOld = page.getByTestId('detail-modal')
  await expect(reopenedOld).toContainText('MART-SNAP-20260829')
  await expect(page.getByTestId('chapter-table').locator('tbody tr', { hasText: '实验' })).toContainText('2026-08-29')

  expect(browserErrors).toEqual([])
})
