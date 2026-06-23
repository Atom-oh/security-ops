/* INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
 * Models a naive funds-transfer handler. Do not ship.
 *   CWE-120  stack buffer overflow via strcpy
 *   CWE-78   OS command injection via system
 *   CWE-787  out-of-bounds write via sprintf
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void process_transfer(const char *user_input, const char *amount) {
    char account[16];
    char cmd[64];
    strcpy(account, user_input);            /* CWE-120: no bounds check */
    sprintf(cmd, "log_transfer %s %s", account, amount); /* CWE-787 */
    system(cmd);                            /* CWE-78: shell injection */
}

int main(int argc, char **argv) {
    if (argc > 2) process_transfer(argv[1], argv[2]);
    return 0;
}
