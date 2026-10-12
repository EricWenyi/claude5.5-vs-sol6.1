/*
 * BedroomClimate.app launcher.
 *
 * macOS only lets a process use Bluetooth if the app "responsible" for it has an
 * NSBluetoothAlwaysUsageDescription in its Info.plist and the user allowed it. A bare
 * python started by launchd has no such app, so it is refused or killed. This tiny
 * executable lives inside an .app bundle that does have the key; it starts python as a
 * child process (children inherit the responsible app), forwards stop signals to it and
 * exits with its status, so launchd's KeepAlive still works.
 *
 * Usage: BedroomClimate <python> -m bedroom_climate [args...]
 */
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static volatile pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <program> [args...]\n", argv[0]);
        return 64;
    }
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = forward;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGHUP, &sa, NULL);

    pid_t pid;
    int err = posix_spawn(&pid, argv[1], NULL, NULL, &argv[1], environ);
    if (err) {
        fprintf(stderr, "BedroomClimate: cannot start %s: %s\n", argv[1], strerror(err));
        return 127;
    }
    child = pid;

    int status;
    while (waitpid(pid, &status, 0) < 0) {
        /* interrupted by a forwarded signal; keep waiting for the child */
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) {
        fprintf(stderr, "BedroomClimate: child killed by signal %d\n", WTERMSIG(status));
        return 128 + WTERMSIG(status);
    }
    return 1;
}
