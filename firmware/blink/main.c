/*
 * Blink LD2 (green, PB0) on a NUCLEO-WB55RG — bare-metal, no HAL.
 *
 * After reset the STM32WB55 runs from the 4 MHz MSI oscillator, so we use
 * that as-is and let SysTick count 1 ms ticks.
 */
#include <stdint.h>

#define REG(addr) (*(volatile uint32_t *)(addr))

/* RCC (reset & clock control) */
#define RCC_BASE        0x58000000UL
#define RCC_AHB2ENR     REG(RCC_BASE + 0x4C)
#define RCC_GPIOBEN     (1UL << 1)

/* GPIOB */
#define GPIOB_BASE      0x48000400UL
#define GPIOB_MODER     REG(GPIOB_BASE + 0x00)
#define GPIOB_ODR       REG(GPIOB_BASE + 0x14)

/* Cortex-M4 SysTick */
#define SYST_CSR        REG(0xE000E010UL)
#define SYST_RVR        REG(0xE000E014UL)
#define SYST_CVR        REG(0xE000E018UL)
#define SYST_COUNTFLAG  (1UL << 16)

#define CPU_HZ          4000000UL   /* MSI default after reset */
#define LED_PIN         0           /* PB0 = LD2 green (PB5 = blue, PB1 = red) */
#define BLINK_MS        500

static void delay_ms(uint32_t ms)
{
    while (ms--) {
        while (!(SYST_CSR & SYST_COUNTFLAG)) {
        }
    }
}

int main(void)
{
    /* 1. Turn on the clock to GPIO port B (peripherals are unclocked at reset). */
    RCC_AHB2ENR |= RCC_GPIOBEN;
    (void)RCC_AHB2ENR;              /* read back: gives the clock a cycle to start */

    /* 2. PB0 as general-purpose output: MODER bits [1:0] = 01. */
    GPIOB_MODER = (GPIOB_MODER & ~(3UL << (LED_PIN * 2))) | (1UL << (LED_PIN * 2));

    /* 3. SysTick: reload every 1 ms from the core clock, no interrupt. */
    SYST_RVR = CPU_HZ / 1000 - 1;
    SYST_CVR = 0;
    SYST_CSR = (1UL << 2) | (1UL << 0);   /* CLKSOURCE = CPU, ENABLE */

    for (;;) {
        GPIOB_ODR ^= (1UL << LED_PIN);
        delay_ms(BLINK_MS);
    }
}
