import React, { useState } from 'react';
import {
  Alert,
  Image,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';

import { useUploadReceipt } from '@/api/receipts';
import { Button } from '@/components/ui/Button';
import { TextInput } from '@/components/ui/TextInput';
import { borderRadius, colors, fontSize, fontWeight, spacing } from '@/theme/tokens';

function todayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function UploadReceiptScreen() {
  const [image, setImage] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [storeName, setStoreName] = useState('');
  const [receiptDate, setReceiptDate] = useState('');
  const uploadReceipt = useUploadReceipt();

  const pickFromLibrary = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Permission required',
        'Please allow access to your photo library in Settings.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Open Settings', onPress: () => Linking.openSettings() },
        ],
      );
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.8,
    });
    if (!result.canceled && result.assets[0]) {
      setImage(result.assets[0]);
    }
  };

  const takePhoto = async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert(
        'Permission required',
        'Please allow access to your camera in Settings.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Open Settings', onPress: () => Linking.openSettings() },
        ],
      );
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      quality: 0.8,
    });
    if (!result.canceled && result.assets[0]) {
      setImage(result.assets[0]);
    }
  };

  const handleUpload = () => {
    if (!image) {
      Alert.alert('No image', 'Please select or take a photo first.');
      return;
    }

    const formData = new FormData();
    formData.append('file', {
      uri: image.uri,
      type: image.mimeType || 'image/jpeg',
      name: image.fileName || 'receipt.jpg',
    } as unknown as Blob);

    if (storeName.trim()) {
      formData.append('store_name', storeName.trim());
    }
    if (receiptDate.trim()) {
      formData.append('receipt_date', receiptDate.trim());
    }

    uploadReceipt.mutate(formData, {
      onSuccess: (data) => {
        router.replace({
          pathname: '/(main)/receipts/[id]',
          params: { id: data.id },
        });
      },
      onError: (err) => {
        Alert.alert('Upload failed', err.message);
      },
    });
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {image ? (
        <Image source={{ uri: image.uri }} style={styles.preview} resizeMode="contain" />
      ) : (
        <View style={styles.placeholder}>
          <Text style={styles.placeholderText}>No image selected</Text>
        </View>
      )}

      <View style={styles.pickerButtons}>
        <Button title="Take Photo" onPress={takePhoto} variant="secondary" style={styles.pickerButton} />
        <Button title="Choose from Library" onPress={pickFromLibrary} variant="secondary" style={styles.pickerButton} />
      </View>

      <TextInput
        label="Store name (optional)"
        value={storeName}
        onChangeText={setStoreName}
        placeholder="e.g. Netto"
      />

      <TextInput
        label="Receipt date (optional, YYYY-MM-DD)"
        value={receiptDate}
        onChangeText={setReceiptDate}
        placeholder={todayStr()}
      />

      <Button
        title="Upload Receipt"
        onPress={handleUpload}
        loading={uploadReceipt.isPending}
        disabled={!image}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  content: {
    padding: spacing.xl,
    paddingBottom: spacing.xxl,
  },
  preview: {
    width: '100%',
    height: 250,
    borderRadius: borderRadius.md,
    backgroundColor: colors.borderLight,
    marginBottom: spacing.lg,
  },
  placeholder: {
    width: '100%',
    height: 250,
    borderRadius: borderRadius.md,
    backgroundColor: colors.borderLight,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  placeholderText: {
    fontSize: fontSize.sm,
    color: colors.textTertiary,
  },
  pickerButtons: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  pickerButton: {
    flex: 1,
  },
});
