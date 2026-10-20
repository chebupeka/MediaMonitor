# Открыть доступ к серверу для выкатки (делает тот, кто настраивал сервер)

Нужно, чтобы ноутбук лида (адрес в интернете `50.7.87.165`) мог заходить на сервер `109.196.167.227` по ключу и выкатывать сервис. Займёт 5 минут.

## Шаг 1. Открыть терминал на своём компьютере

- **Windows:** Пуск → «PowerShell».
- **Mac:** программа «Терминал».
- **Linux:** любой терминал.

## Шаг 2. Зайти на сервер

```
ssh team-27@109.196.167.227
```

- Если спросит `Are you sure you want to continue connecting (yes/no)?`, напишите `yes` и нажмите Enter.
- Если спросит пароль, введите пароль пользователя team-27 (его знает тот, кто настраивал сервер). Символы при вводе не видны, так и должно быть.
- Когда вход удался, слева появится что-то вроде `team-27@имя-сервера:~$`. Теперь вы на сервере, и все команды ниже выполняются там.

## Шаг 3. Вставить команды

Скопируйте блок целиком и вставьте в то же окно: в PowerShell правой кнопкой мыши, на Mac — Cmd+V. Нажмите Enter. Если `sudo` спросит пароль, введите тот же пароль пользователя team-27.

```
IP=50.7.87.165
sudo journalctl -u ssh -u sshd --since today | grep "$IP" | tail -5
sudo fail2ban-client set sshd unbanip $IP
echo -e "[DEFAULT]\nignoreip = 127.0.0.1/8 ::1 $IP" | sudo tee /etc/fail2ban/jail.d/mediamonitor-allow.local
sudo systemctl restart fail2ban
sudo ufw allow from $IP to any port 22 proto tcp
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'from="50.7.87.165" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP2Y/tlFYfRdNA+Culmq6o7TMlmmQEMtVYlYX5IvmCmc mediamonitor-laptop-deploy' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
docker --version; docker compose version
sudo usermod -aG docker team-27
```

## Что вы увидите (это нормально)

| Команда | Нормальный ответ |
|---|---|
| `journalctl … grep` | несколько строк с `50.7.87.165` или пусто |
| `unbanip` | `1`, `0` или «IP is not banned» |
| `fail2ban-client` / `systemctl … fail2ban` | если «command not found» или «not found» — fail2ban не установлен, пропускаем |
| `tee …` | одна строка `[DEFAULT] ignoreip = …` |
| `ufw allow` | «Rule added», «Skipping adding existing rule» или «command not found» (ufw нет — тоже нормально) |
| `docker --version` | `Docker version 2x.x…`; если «command not found» — Docker не установлен, напишите лиду |
| остальное | без ответа |

Если у вас в fail2ban уже были свои исключения (`ignoreip`), допишите их в ту же строку в файле `/etc/fail2ban/jail.d/mediamonitor-allow.local`.

## Шаг 4. Выйти и прислать вывод

```
exit
```

Скопируйте всё, что появилось в окне после шага 3, и пришлите лиду. Он проверит вход по ключу и выкатит сервис.

**Если в панели хостинга включён свой брандмауэр,** разрешите там `50.7.87.165` на порт 22.

**Безопасность:** ключ работает только с адреса `50.7.87.165`. После того как лид подтвердит вход, смените пароль пользователя team-27 командой `passwd` на сервере: старый пароль был в переписке.

## Снять ограничение ключа по адресу (20.10.2026)

Ограничение `from="…"` на ключе ноутбука лида пришлось менять уже дважды: при смене сети меняется адрес ноутбука в интернете, и сервер перестаёт пускать ключ. Решили снять ограничение, ключ остаётся только на ноутбуке лида.

Зайти на сервер, как в шаге 2, и вставить:

```
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
sed -i '/mediamonitor-laptop-deploy/ s/^from="[^"]*" //' ~/.ssh/authorized_keys
grep mediamonitor-laptop-deploy ~/.ssh/authorized_keys | cut -c1-30
```

Последняя команда должна вывести строку, которая начинается с `ssh-ed25519 AAAA`, без `from=`. Меняется только строка ключа лида, остальные ключи не трогаются; копия прежнего файла — `~/.ssh/authorized_keys.bak`.

Если лид после этого всё равно не может войти, его новый адрес мог попасть в бан fail2ban из-за неудачных попыток. Разбанить всех:

```
sudo fail2ban-client unban --all
```
