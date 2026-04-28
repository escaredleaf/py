package com.example.phonecallapp

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    private lateinit var phoneInput: EditText
    private lateinit var callButton: Button

    private val requestCallPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted ->
            if (isGranted) {
                performPhoneCall()
            } else {
                Toast.makeText(this, getString(R.string.error_permission_denied), Toast.LENGTH_SHORT).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        phoneInput = findViewById(R.id.phoneEditText)
        callButton = findViewById(R.id.callButton)

        callButton.setOnClickListener {
            if (hasCallPermission()) {
                performPhoneCall()
            } else {
                requestCallPermissionLauncher.launch(Manifest.permission.CALL_PHONE)
            }
        }
    }

    private fun hasCallPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.CALL_PHONE
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun performPhoneCall() {
        val phoneNumber = phoneInput.text.toString().trim()
        if (phoneNumber.isEmpty()) {
            Toast.makeText(this, getString(R.string.error_empty_phone), Toast.LENGTH_SHORT).show()
            return
        }

        val callIntent = Intent(Intent.ACTION_CALL).apply {
            data = Uri.parse("tel:$phoneNumber")
        }

        if (hasCallPermission()) {
            try {
                startActivity(callIntent)
            } catch (_: Exception) {
                Toast.makeText(this, getString(R.string.error_cannot_call), Toast.LENGTH_SHORT).show()
            }
        } else {
            Toast.makeText(this, getString(R.string.error_permission_denied), Toast.LENGTH_SHORT).show()
        }
    }
}
