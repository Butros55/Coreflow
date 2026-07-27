// eslint-config-next 16 ships native flat configs, so FlatCompat is neither
// needed nor workable here (compat-loading it hits a circular-structure error
// in @eslint/eslintrc). Import the flat configs directly.
import coreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

const config = [
  ...coreWebVitals,
  ...nextTypescript,
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'next-env.d.ts',
    ],
  },
  {
    rules: {
      // Unused vars are an error, but a leading underscore marks a deliberate
      // omission (e.g. an unused callback arg whose position matters).
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      '@typescript-eslint/no-explicit-any': 'error',
      // console.log left in shipped code can leak customer data into the browser
      // console; warn/error are intentional.
      'no-console': ['error', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
    },
  },
  {
    // Tests may reach for `any` when stubbing, and log freely.
    files: ['**/*.test.ts', '**/*.test.tsx', 'e2e/**/*.ts', 'vitest.setup.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'no-console': 'off',
    },
  },
];

export default config;
