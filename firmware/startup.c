/*
 * Minimal startup for STM32WB55 (Cortex-M4): vector table + reset handler.
 * The reset handler prepares RAM the way C expects, then calls main().
 */
#include <stdint.h>

extern uint32_t _estack;                 /* top of RAM, from link.ld */
extern uint32_t _sidata, _sdata, _edata; /* .data: load address in flash, run range in RAM */
extern uint32_t _sbss, _ebss;            /* .bss: RAM to zero */

int main(void);
void SysTick_Handler(void);

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    for (uint32_t *dst = &_sdata; dst < &_edata; )
        *dst++ = *src++;
    for (uint32_t *dst = &_sbss; dst < &_ebss; )
        *dst++ = 0;

    main();
    for (;;) {
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}

/* First two words are what the CPU reads at reset: initial SP, then entry point. */
__attribute__((section(".isr_vector"), used))
void (*const vector_table[16])(void) = {
    (void (*)(void))&_estack,
    Reset_Handler,
    Default_Handler, /* NMI */
    Default_Handler, /* HardFault */
    Default_Handler, /* MemManage */
    Default_Handler, /* BusFault */
    Default_Handler, /* UsageFault */
    0, 0, 0, 0,
    Default_Handler, /* SVCall */
    Default_Handler, /* DebugMon */
    0,
    Default_Handler, /* PendSV */
    SysTick_Handler,
};
