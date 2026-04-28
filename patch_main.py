old_section = '''            if not edited:
            last_created_str = get_config('alternate_digest_last_created')
            last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
            time_since_last = time.time() - last_created
            logger.info(f"alternate_digest_job: last_created={last_created}, time_since_last={time_since_last:.0f}sec")
            if time_since_last < 60:
                logger.info(f"Пропускаем создание нового дайджеста, прошло только {time_since_last:.0f} sec")
                return

            # Удаляем старое сообщение
            if last_message_id:
                try:
                    msg_id_int = int(last_message_id)
                    if msg_id_int > 0:
                        await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                        logger.info(f"Удалено старое alternate сообщение {last_message_id}")
                    else:
                        logger.warning(f"Invalid last_message_id for deletion: {last_message_id}")
                        set_config('alternate_digest_message_id', None)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid alternate_digest_message_id format for deletion: {last_message_id}, error: {e}")
                    set_config('alternate_digest_message_id', None)
                except Exception as e:
                    error_str = str(e).lower()
                    if "message to delete not found" in error_str or "message can't be deleted" in error_str or "bad request" in error_str:
                        logger.debug(f"Старое сообщение {last_message_id} уже удалено")
                    else:
                        logger.debug(f"Не удалось удалить старое alternate сообщение: {e}")
            set_config('alternate_digest_message_id', None)

            # Создаём новое сообщение
            try:
                msg = await bot.send_message(
                    chat_id=int(digest_chat_id),
                    text=text,
                    parse_mode="HTML"
                )
                set_config('alternate_digest_message_id', str(msg.message_id))
                set_config('alternate_digest_last_created', str(time.time()))
                set_config('alternate_digest_type', next_type)
                _digest_state["type"] = next_type
                _digest_state["last_text"] = text
                logger.info(f"Создано новое alternate сообщение {msg.message_id}")
            except Exception as e:
                logger.error(f"Ошибка создания сообщения: {e}")'''

new_section = '''            if not edited:
                # Генерируем геро-мета баннер
                hero_meta_banner = None
                try:
                    from hero_meta import get_hero_meta_image
                    hero_meta_banner = get_hero_meta_image()
                    logger.info("Hero meta banner generated for digest")
                except Exception as e:
                    logger.warning(f"Could not generate hero meta banner: {e}")

                # Проверяем анти-спам
                last_created_str = get_config('alternate_digest_last_created')
                last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
                time_since_last = time.time() - last_created
                if time_since_last < 60:
                    logger.info(f"Пропускаем - прошло всего {time_since_last:.0f} сек с последнего создания")
                    return

                # Удаляем старое сообщение если есть
                if last_message_id:
                    try:
                        msg_id_int = int(last_message_id)
                        if msg_id_int > 0:
                            await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                            logger.info(f"Удалено старое сообщение {last_message_id}")
                    except Exception as e:
                        logger.debug(f"Старое сообщение уже удалено: {e}")
                set_config('alternate_digest_message_id', None)

                # Создаём новое сообщение
                try:
                    from io import BytesIO
                    if hero_meta_banner:
                        photo_buf = BytesIO(hero_meta_banner)
                        photo_buf.name = "hero_meta_banner.png"
                        msg = await bot.send_photo(
                            chat_id=int(digest_chat_id),
                            photo=photo_buf,
                            caption=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"Создан новый дайджест с фото {msg.message_id}")
                    else:
                        msg = await bot.send_message(
                            chat_id=int(digest_chat_id),
                            text=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"Создан новый дайджест (текст) {msg.message_id}")

                    set_config('alternate_digest_message_id', str(msg.message_id))
                    set_config('alternate_digest_last_created', str(time.time()))
                    set_config('alternate_digest_type', next_type)
                    _digest_state["type"] = next_type
                    _digest_state["last_text"] = text
                except Exception as e:
                    logger.error(f"Ошибка создания сообщения: {e}")
                    set_config('alternate_digest_message_id', None)'''

new_section = '''            if not edited:
                # Генерируем геро-мета баннер
                hero_meta_banner = None
                try:
                    from hero_meta import get_hero_meta_image
                    hero_meta_banner = get_hero_meta_image()
                    logger.info("Hero meta banner generated for digest")
                except Exception as e:
                    logger.warning(f"Could not generate hero meta banner: {e}")

                # Проверяем анти-спам
                last_created_str = get_config('alternate_digest_last_created')
                last_created = float(last_created_str) if last_created_str and last_created_str.strip() else 0
                time_since_last = time.time() - last_created
                if time_since_last < 60:
                    logger.info(f"Пропускаем - прошло всего {time_since_last:.0f} сек с последнего создания")
                    return

                # Удаляем старое сообщение если есть
                if last_message_id:
                    try:
                        msg_id_int = int(last_message_id)
                        if msg_id_int > 0:
                            await bot.delete_message(chat_id=int(digest_chat_id), message_id=msg_id_int)
                            logger.info(f"Удалено старое сообщение {last_message_id}")
                    except Exception as e:
                        logger.debug(f"Старое сообщение уже удалено: {e}")
                set_config('alternate_digest_message_id', None)

                # Создаём новое сообщение
                try:
                    from io import BytesIO
                    if hero_meta_banner:
                        photo_buf = BytesIO(hero_meta_banner)
                        photo_buf.name = "hero_meta_banner.png"
                        msg = await bot.send_photo(
                            chat_id=int(digest_chat_id),
                            photo=photo_buf,
                            caption=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"Создан новый дайджест с фото {msg.message_id}")
                    else:
                        msg = await bot.send_message(
                            chat_id=int(digest_chat_id),
                            text=text,
                            parse_mode="HTML"
                        )
                        logger.info(f"Создан новый дайджест (текст) {msg.message_id}")

                    set_config('alternate_digest_message_id', str(msg.message_id))
                    set_config('alternate_digest_last_created', str(time.time()))
                    set_config('alternate_digest_type', next_type)
                    _digest_state["type"] = next_type
                    _digest_state["last_text"] = text
                except Exception as e:
                    logger.error(f"Ошибка создания сообщения: {e}")
                    set_config('alternate_digest_message_id', None)'''