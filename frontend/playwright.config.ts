import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'../tests/e2e',timeout:30000,workers:1,use:{baseURL:process.env.GT7_TEST_URL||'http://127.0.0.1:8000',headless:true,channel:process.env.PW_CHANNEL||'chrome'},reporter:'list'});
