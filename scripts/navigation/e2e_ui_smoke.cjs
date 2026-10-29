/**
 * Browser smoke test for the navigation workbench against the synthetic
 * research stack. Requires backend/worker/frontend running locally.
 *
 * Run from the frontend directory:
 *   node ../scripts/navigation/e2e_ui_smoke.cjs
 */
const path = require('node:path')
const fs = require('node:fs')
const { createRequire } = require('node:module')

const frontendRoot = path.resolve(__dirname, '../../frontend')
const requireFromFrontend = createRequire(path.join(frontendRoot, 'package.json'))
const { chromium } = requireFromFrontend('playwright')

const BASE = process.env.E2E_UI_BASE || 'http://127.0.0.1:5173'
const OUTPUT = path.resolve(__dirname, '../../output')
fs.mkdirSync(OUTPUT, { recursive: true })

async function main() {
  const chromePath =
    process.env.E2E_CHROME_PATH ||
    'C:/Users/liyang/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe'
  const browser = await chromium.launch({
    headless: true,
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(String(error)))

  try {
    await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
    await page.getByPlaceholder('请输入用户名').fill('admin')
    await page.getByPlaceholder('请输入密码').fill('AdminPass123!')
    await page.getByRole('button', { name: '登录系统' }).click()
    await page.waitForURL('**/projects', { timeout: 30000 })

    await page.locator('.project-card').first().click()
    await page.waitForURL('**/map/**', { timeout: 30000 })
    await page.locator('.map-workspace').waitFor({ timeout: 30000 })
    await page.waitForTimeout(2500)

    await page.locator('.map-tools button').nth(4).click()
    await page.getByText('航路规划模拟', { exact: true }).waitFor({ timeout: 10000 })
    await page.getByRole('button', { name: '智能规划' }).click()
    await page.getByText('开始智能规划', { exact: true }).waitFor({ timeout: 10000 })

    const numbers = page.locator('.navigation-coordinate-row .el-input-number input')
    await numbers.nth(0).fill('120')
    await numbers.nth(1).fill('75')
    await numbers.nth(2).fill('122')
    await numbers.nth(3).fill('77')
    await page.getByText('合成研究数据', { exact: true }).click()
    await page.getByRole('button', { name: '开始智能规划' }).click()

    await page.locator('.el-tabs__item').filter({ hasText: '结果' }).click()
    await page
      .locator('.planning-result-heading .el-tag')
      .filter({ hasText: '已完成' })
      .waitFor({ timeout: 180000 })
    await page.screenshot({ path: path.join(OUTPUT, 'navigation-e2e-result.png') })

    await page.locator('.el-tabs__item').filter({ hasText: '候选对比' }).click()
    await page.locator('.el-table__row').first().waitFor({ timeout: 30000 })
    // Select a row, then adopt the selected/recommended candidate.
    await page.locator('.el-table__row').first().click()
    await page.getByRole('button', { name: '采纳' }).first().click()
    await page.getByText('规划快照（只读）', { exact: true }).waitFor({ timeout: 15000 })

    // Edit the first longitude; the old planning metrics must become stale.
    const pointInputs = page.locator('.route-point-table input')
    await pointInputs.first().fill('120.5')
    await pointInputs.first().press('Enter')
    await page.getByText('当前航线已修改，风险和能耗结果需要重新计算', { exact: true }).waitFor({
      timeout: 15000,
    })
    await page.screenshot({ path: path.join(OUTPUT, 'navigation-e2e-stale.png') })

    await page.getByRole('button', { name: '按当前航线重新评估' }).click()
    await page.getByText('已按当前规划快照重新评估', { exact: true }).first().waitFor({
      timeout: 30000,
    })
    await page.getByText('规划快照（只读）', { exact: true }).waitFor({ timeout: 15000 })

    await page.getByRole('button', { name: '智能规划' }).click()
    await page.locator('.el-tabs__item').filter({ hasText: '风险' }).click()
    await page.getByRole('button', { name: '加载风险格' }).click()
    await page.locator('.risk-grid-summary').waitFor({ timeout: 30000 })
    await page.screenshot({ path: path.join(OUTPUT, 'navigation-e2e-risk.png') })

    if (pageErrors.length) {
      throw new Error(`Page errors: ${pageErrors.join(' | ')}`)
    }
    console.log('UI smoke OK: login → map → smart plan → completed → compare → adopt → edit → stale → reevaluate → risk grid')
    console.log(`Screenshots: ${OUTPUT}`)
  } finally {
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
