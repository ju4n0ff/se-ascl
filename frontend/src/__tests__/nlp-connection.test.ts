/**
 * Test: NLP Dictionary Connection
 *
 * Verifies that dynamic sign glosses are correctly translated to Spanish
 * through the nlp-lsch dictionary. This test can be run manually or
 * as part of the CI pipeline.
 *
 * Run: npx tsx apps/web-demo/src/__tests__/nlp-connection.test.ts
 */

import { lookupSign, signsToSpanish } from '@senascl/nlp-lsch';
import { RecognitionResult, ConfidenceLevel } from '@senascl/shared-types';

// Test cases: gloss → expected Spanish text
const TEST_CASES: Array<{ gloss: string; expected: string }> = [
  { gloss: 'HOLA', expected: 'hola' },
  { gloss: 'GRACIAS', expected: 'gracias' },
  { gloss: 'POR_FAVOR', expected: 'por favor' },
  { gloss: 'SI', expected: 'sí' },
  { gloss: 'NO', expected: 'no' },
  { gloss: 'YO', expected: 'yo' },
  { gloss: 'TU', expected: 'tú' },
  { gloss: 'AYUDA', expected: 'ayuda' },
  { gloss: 'BIEN', expected: 'bien' },
  { gloss: 'TRABAJO', expected: 'trabajo' },
  { gloss: 'FAMILIA', expected: 'familia' },
  { gloss: 'AMIGO', expected: 'amigo' },
  { gloss: 'CASA', expected: 'casa' },
  { gloss: 'AGUA', expected: 'agua' },
  { gloss: 'COMIDA', expected: 'comida' },
];

// Test lookupSign function
function testLookupSign(): boolean {
  console.log('Testing lookupSign...');
  let passed = 0;
  let failed = 0;

  for (const { gloss, expected } of TEST_CASES) {
    const result = lookupSign(gloss);
    if (result === expected) {
      console.log(`  ✓ ${gloss} → "${result}"`);
      passed++;
    } else {
      console.log(`  ✗ ${gloss} → "${result}" (expected "${expected}")`);
      failed++;
    }
  }

  console.log(`  Results: ${passed} passed, ${failed} failed\n`);
  return failed === 0;
}

// Test signsToSpanish with dynamic signs
function testSignsToSpanish(): boolean {
  console.log('Testing signsToSpanish with dynamic signs...');
  let passed = 0;
  let failed = 0;

  // Create mock RecognitionResults as if they came from the temporal model
  const mockResults: RecognitionResult[] = TEST_CASES.slice(0, 5).map(({ gloss, expected }) => ({
    signId: gloss,
    gloss,
    spanishText: lookupSign(gloss) ?? gloss,
    confidence: 0.85,
    confidenceLevel: ConfidenceLevel.HIGH,
    timestamp: Date.now(),
    isFingerspelling: false,
  }));

  // Test each result individually
  for (const result of mockResults) {
    const expected = TEST_CASES.find(tc => tc.gloss === result.gloss)?.expected;
    if (result.spanishText === expected) {
      console.log(`  ✓ ${result.gloss} → "${result.spanishText}"`);
      passed++;
    } else {
      console.log(`  ✗ ${result.gloss} → "${result.spanishText}" (expected "${expected}")`);
      failed++;
    }
  }

  // Test concatenation of multiple signs
  const combinedText = signsToSpanish(mockResults);
  const expectedCombined = 'hola gracias por favor sí no';
  if (combinedText === expectedCombined) {
    console.log(`  ✓ Combined: "${combinedText}"`);
    passed++;
  } else {
    console.log(`  ✗ Combined: "${combinedText}" (expected "${expectedCombined}")`);
    failed++;
  }

  console.log(`  Results: ${passed} passed, ${failed} failed\n`);
  return failed === 0;
}

// Test unknown gloss handling
function testUnknownGloss(): boolean {
  console.log('Testing unknown gloss handling...');

  const unknownGloss = 'PALABRA_INVENTADA';
  const result = lookupSign(unknownGloss);

  if (result === undefined) {
    console.log(`  ✓ Unknown gloss "${unknownGloss}" returns undefined`);
    console.log(`  ✓ Fallback behavior: use gloss as-is (${unknownGloss})`);
    return true;
  } else {
    console.log(`  ✗ Unknown gloss "${unknownGloss}" returned "${result}" instead of undefined`);
    return false;
  }
}

// Run all tests
function runTests(): void {
  console.log('=' .repeat(60));
  console.log('NLP CONNECTION TEST - SeñasCL');
  console.log('=' .repeat(60));
  console.log('');

  const results: Array<{ name: string; passed: boolean }> = [];

  results.push({ name: 'lookupSign', passed: testLookupSign() });
  results.push({ name: 'signsToSpanish', passed: testSignsToSpanish() });
  results.push({ name: 'unknownGloss', passed: testUnknownGloss() });

  console.log('=' .repeat(60));
  console.log('SUMMARY');
  console.log('=' .repeat(60));

  let allPassed = true;
  for (const { name, passed } of results) {
    const status = passed ? '✓' : '✗';
    console.log(`  ${status} ${name}`);
    if (!passed) allPassed = false;
  }

  console.log('');
  if (allPassed) {
    console.log('✓ ALL TESTS PASSED - NLP connection is working correctly');
  } else {
    console.log('✗ SOME TESTS FAILED - Check the output above');
  }
  console.log('=' .repeat(60));
}

runTests();
