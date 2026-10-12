package com.secondbrain.app

import android.content.Context
import android.provider.CalendarContract
import java.time.Instant
import java.time.ZoneId

data class CalendarEvent(
    val externalId: String,
    val title: String,
    val startAt: String,
    val endAt: String,
    val allDay: Boolean,
    val location: String,
    val description: String,
    val calendarName: String,
)

/** Reads expanded Calendar Provider instances only; this object has no write APIs. */
object CalendarReader {
    private const val MAX_EVENTS = 200

    fun recent(context: Context, startMillis: Long, endMillis: Long): List<CalendarEvent> {
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon()
            .appendPath(startMillis.toString())
            .appendPath(endMillis.toString())
            .build()
        val projection = arrayOf(
            CalendarContract.Instances.EVENT_ID,
            CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END,
            CalendarContract.Instances.TITLE,
            CalendarContract.Instances.ALL_DAY,
            CalendarContract.Instances.EVENT_LOCATION,
            CalendarContract.Instances.DESCRIPTION,
            CalendarContract.Instances.CALENDAR_DISPLAY_NAME,
        )
        return context.contentResolver.query(uri, projection, null, null, "${CalendarContract.Instances.BEGIN} ASC")?.use { cursor ->
            val eventId = cursor.getColumnIndexOrThrow(CalendarContract.Instances.EVENT_ID)
            val begin = cursor.getColumnIndexOrThrow(CalendarContract.Instances.BEGIN)
            val end = cursor.getColumnIndexOrThrow(CalendarContract.Instances.END)
            val title = cursor.getColumnIndexOrThrow(CalendarContract.Instances.TITLE)
            val allDay = cursor.getColumnIndexOrThrow(CalendarContract.Instances.ALL_DAY)
            val location = cursor.getColumnIndexOrThrow(CalendarContract.Instances.EVENT_LOCATION)
            val description = cursor.getColumnIndexOrThrow(CalendarContract.Instances.DESCRIPTION)
            val calendar = cursor.getColumnIndexOrThrow(CalendarContract.Instances.CALENDAR_DISPLAY_NAME)
            buildList {
                while (cursor.moveToNext() && size < MAX_EVENTS) {
                    val start = cursor.getLong(begin)
                    add(CalendarEvent(
                        // A recurring event's provider id is shared, so include its instance begin.
                        externalId = "${cursor.getLong(eventId)}:$start",
                        title = cursor.stringAt(title).ifBlank { "（无标题日程）" }.take(500),
                        startAt = start.toIso(), endAt = cursor.getLong(end).toIso(),
                        allDay = cursor.getInt(allDay) != 0,
                        location = cursor.stringAt(location).take(1000),
                        description = cursor.stringAt(description).take(4000),
                        calendarName = cursor.stringAt(calendar).take(200),
                    ))
                }
            }
        } ?: emptyList()
    }

    private fun android.database.Cursor.stringAt(index: Int): String = if (isNull(index)) "" else getString(index).orEmpty()
    private fun Long.toIso(): String = Instant.ofEpochMilli(this).atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()
}
