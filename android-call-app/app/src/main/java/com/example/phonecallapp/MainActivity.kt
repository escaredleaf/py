package com.example.phonecallapp

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import java.io.IOException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private lateinit var backendUrlInput: EditText
    private lateinit var startCallButton: Button
    private lateinit var endCallButton: Button
    private lateinit var statusText: TextView

    private val ioExecutor = Executors.newSingleThreadExecutor()
    private val httpClient = OkHttpClient.Builder()
        .callTimeout(30, TimeUnit.SECONDS)
        .build()

    private var peerConnectionFactory: PeerConnectionFactory? = null
    private var peerConnection: PeerConnection? = null
    private var localAudioSource: AudioSource? = null
    private var localAudioTrack: AudioTrack? = null
    private var eglBase: EglBase? = null
    @Volatile
    private var callActive = false

    private data class SessionToken(
        val clientSecret: String,
        val model: String
    )

    private val audioPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted ->
            if (isGranted) {
                startWebRtcCall()
            } else {
                showToast(R.string.error_permission_audio)
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        backendUrlInput = findViewById(R.id.backendUrlInput)
        startCallButton = findViewById(R.id.startCallButton)
        endCallButton = findViewById(R.id.endCallButton)
        statusText = findViewById(R.id.statusText)

        backendUrlInput.setText("http://10.0.2.2:8000/session")
        renderIdleState()

        startCallButton.setOnClickListener {
            if (hasAudioPermission()) {
                startWebRtcCall()
            } else {
                audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            }
        }

        endCallButton.setOnClickListener {
            endCall()
        }
    }

    override fun onDestroy() {
        endCall()
        ioExecutor.shutdown()
        super.onDestroy()
    }

    private fun startWebRtcCall() {
        val backendUrl = backendUrlInput.text.toString().trim()
        if (backendUrl.isEmpty()) {
            showToast(R.string.error_backend_url)
            return
        }

        updateStatus(getString(R.string.state_connecting))
        startCallButton.isEnabled = false
        endCallButton.isEnabled = false

        ioExecutor.execute {
            try {
                val tokenResponse = fetchEphemeralToken(backendUrl)
                setupPeerConnectionFactory()
                val localPeer = createPeerConnection()
                val offer = createOffer(localPeer)
                setLocalDescription(localPeer, offer)
                val answerSdp = exchangeOfferForAnswer(
                    clientSecret = tokenResponse.clientSecret,
                    model = tokenResponse.model,
                    offerSdp = offer.description
                )
                setRemoteDescription(localPeer, SessionDescription(SessionDescription.Type.ANSWER, answerSdp))
                callActive = true

                runOnUiThread {
                    updateStatus(getString(R.string.state_connected))
                    startCallButton.isEnabled = false
                    endCallButton.isEnabled = true
                }
            } catch (_: Exception) {
                runOnUiThread {
                    updateStatus(getString(R.string.state_idle))
                    startCallButton.isEnabled = true
                    endCallButton.isEnabled = false
                    showToast(R.string.error_webrtc)
                }
                releasePeerConnection()
            }
        }
    }

    private fun endCall() {
        if (!callActive && peerConnection == null) {
            renderIdleState()
            return
        }
        updateStatus(getString(R.string.state_ending))
        releasePeerConnection()
        renderIdleState()
    }

    private fun renderIdleState() {
        updateStatus(getString(R.string.state_idle))
        startCallButton.isEnabled = true
        endCallButton.isEnabled = false
    }

    private fun fetchEphemeralToken(backendUrl: String): SessionToken {
        val request = Request.Builder()
            .url(backendUrl)
            .post("{}".toRequestBody("application/json".toMediaType()))
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException(getString(R.string.error_network))
            }
            val body = response.body?.string().orEmpty()
            val json = JSONObject(body)
            return SessionToken(
                clientSecret = json.getString("client_secret"),
                model = json.optString("model", "gpt-4o-realtime-preview")
            )
        }
    }

    private fun setupPeerConnectionFactory() {
        if (peerConnectionFactory != null) return

        eglBase = EglBase.create()
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(this)
                .createInitializationOptions()
        )
        val encoderFactory = DefaultVideoEncoderFactory(eglBase?.eglBaseContext, true, true)
        val decoderFactory = DefaultVideoDecoderFactory(eglBase?.eglBaseContext)
        peerConnectionFactory = PeerConnectionFactory.builder()
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .createPeerConnectionFactory()
    }

    private fun createPeerConnection(): PeerConnection {
        val iceServers = listOf(
            PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
        )
        val rtcConfig = PeerConnection.RTCConfiguration(iceServers)
        val localFactory = peerConnectionFactory ?: throw IllegalStateException("Factory not initialized")

        val audioConstraints = MediaConstraints()
        localAudioSource = localFactory.createAudioSource(audioConstraints)
        localAudioTrack = localFactory.createAudioTrack("local_audio_track", localAudioSource)

        val createdPeer = localFactory.createPeerConnection(rtcConfig, object : PeerConnection.Observer {
            override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = Unit
            override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) = Unit
            override fun onIceCandidate(candidate: IceCandidate) = Unit
            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
            override fun onAddStream(stream: MediaStream) = Unit
            override fun onRemoveStream(stream: MediaStream) = Unit
            override fun onDataChannel(channel: DataChannel) = Unit
            override fun onRenegotiationNeeded() = Unit
            override fun onAddTrack(receiver: RtpReceiver, mediaStreams: Array<out MediaStream>) = Unit
        }) ?: throw IllegalStateException("Failed to create PeerConnection")

        createdPeer.addTrack(
            localAudioTrack ?: throw IllegalStateException("Audio track unavailable"),
            listOf("local_audio_stream")
        )
        peerConnection = createdPeer
        return createdPeer
    }

    private fun createOffer(peer: PeerConnection): SessionDescription {
        val constraints = MediaConstraints().apply {
            mandatory.add(MediaConstraints.KeyValuePair("OfferToReceiveAudio", "true"))
        }
        var offer: SessionDescription? = null
        var error: String? = null
        val lock = Object()
        peer.createOffer(object : SdpObserver {
            override fun onCreateSuccess(sessionDescription: SessionDescription?) {
                synchronized(lock) {
                    offer = sessionDescription
                    lock.notifyAll()
                }
            }

            override fun onSetSuccess() = Unit
            override fun onCreateFailure(reason: String?) {
                synchronized(lock) {
                    error = reason ?: "offer failure"
                    lock.notifyAll()
                }
            }

            override fun onSetFailure(reason: String?) = Unit
        }, constraints)
        synchronized(lock) {
            if (offer == null && error == null) lock.wait(15000)
        }
        if (error != null || offer == null) {
            throw IllegalStateException(error ?: "offer timeout")
        }
        return offer as SessionDescription
    }

    private fun setLocalDescription(peer: PeerConnection, sessionDescription: SessionDescription) {
        val lock = Object()
        var error: String? = null
        var done = false
        peer.setLocalDescription(object : SdpObserver {
            override fun onSetSuccess() {
                synchronized(lock) {
                    done = true
                    lock.notifyAll()
                }
            }

            override fun onSetFailure(reason: String?) {
                synchronized(lock) {
                    done = true
                    error = reason ?: "setLocalDescription failure"
                    lock.notifyAll()
                }
            }

            override fun onCreateSuccess(sessionDescription: SessionDescription?) = Unit
            override fun onCreateFailure(reason: String?) = Unit
        }, sessionDescription)
        synchronized(lock) {
            if (!done) lock.wait(15000)
        }
        if (!done) throw IllegalStateException("setLocalDescription timeout")
        if (error != null) throw IllegalStateException(error)
    }

    private fun exchangeOfferForAnswer(clientSecret: String, model: String, offerSdp: String): String {
        val requestBody = offerSdp.toRequestBody("application/sdp".toMediaType())
        val request = Request.Builder()
            .url("https://api.openai.com/v1/realtime?model=$model")
            .addHeader("Authorization", "Bearer $clientSecret")
            .addHeader("OpenAI-Beta", "realtime=v1")
            .addHeader("Content-Type", "application/sdp")
            .post(requestBody)
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException(getString(R.string.error_network))
            }
            return response.body?.string().orEmpty()
        }
    }

    private fun setRemoteDescription(peer: PeerConnection, sessionDescription: SessionDescription) {
        val lock = Object()
        var error: String? = null
        var done = false
        peer.setRemoteDescription(object : SdpObserver {
            override fun onSetSuccess() {
                synchronized(lock) {
                    done = true
                    lock.notifyAll()
                }
            }

            override fun onSetFailure(reason: String?) {
                synchronized(lock) {
                    done = true
                    error = reason ?: "setRemoteDescription failure"
                    lock.notifyAll()
                }
            }

            override fun onCreateSuccess(sessionDescription: SessionDescription?) = Unit
            override fun onCreateFailure(reason: String?) = Unit
        }, sessionDescription)
        synchronized(lock) {
            if (!done) lock.wait(15000)
        }
        if (!done) throw IllegalStateException("setRemoteDescription timeout")
        if (error != null) throw IllegalStateException(error)
    }

    private fun releasePeerConnection() {
        callActive = false
        localAudioTrack?.dispose()
        localAudioTrack = null
        localAudioSource?.dispose()
        localAudioSource = null
        peerConnection?.close()
        peerConnection?.dispose()
        peerConnection = null
        peerConnectionFactory?.dispose()
        peerConnectionFactory = null
        eglBase?.release()
        eglBase = null
    }

    private fun hasAudioPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun updateStatus(message: String) {
        runOnUiThread { statusText.text = message }
    }

    private fun showToast(messageResId: Int) {
        Toast.makeText(this, getString(messageResId), Toast.LENGTH_SHORT).show()
    }
}
